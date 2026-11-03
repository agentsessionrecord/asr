//! fx committed event prefixes. Uncommitted bytes and replacement encodings are never exported.
use crate::{
    batch_a as b,
    common::{self, Context},
    spool::Spool,
    Agent, Error, Result, Summary,
};
use asr_core::jsonl::{Line, Reader};
use base64::{engine::general_purpose::STANDARD, Engine};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    fs::File,
    io::{BufReader, Read, Seek, SeekFrom},
    path::Path,
};

fn invalid() -> Error {
    Error::Invalid("invalid or changing fx committed store".into())
}
fn hex(v: &Value, len: usize) -> bool {
    v.as_str().is_some_and(|s| {
        s.len() == len
            && s.bytes()
                .all(|v| v.is_ascii_digit() || (b'a'..=b'f').contains(&v))
    })
}
pub fn stage(s: &mut Spool, p: &Path, n: &mut Summary) -> Result<()> {
    let dir = p.parent().unwrap();
    if !dir.join("authority.json").is_file() {
        n.files += 1;
        n.diagnostic("unidentified_source");
        return Ok(());
    }
    for pending in ["authority.pending.json", "commit.pending.json"] {
        if dir.join(pending).exists() {
            return Err(invalid());
        }
    }
    let a = b::document(&dir.join("authority.json"), s.limit)?;
    let id = b::nonempty(&a["session_id"]).ok_or_else(invalid)?;
    if a["schema_version"] != 1
        || a["storage_format"] != "event_log_v1"
        || !hex(&a["authority_id"], 32)
    {
        return Err(invalid());
    }
    let mut first_reader = Reader::new(b::reader(p)?, s.limit);
    let Some(Line::Record(first)) = first_reader.read()? else {
        return Err(invalid());
    };
    if first["kind"] != "session_started"
        || first["payload"]["id"] != id
        || !hex(&first["log_generation"], 32)
    {
        return Err(invalid());
    }
    let generation = first["log_generation"].as_str().unwrap();
    let wm_path = dir.join(format!("commit.{generation}.json"));
    let wm = b::document(&wm_path, s.limit)?;
    if wm["schema_version"] != 1
        || wm["session_id"] != id
        || wm["log_generation"] != generation
        || !hex(&wm["through_event_id"], 32)
    {
        return Err(invalid());
    }
    let size = wm["through_event_log_bytes"].as_u64().ok_or_else(invalid)?;
    let through = wm["through_seq"].as_u64().ok_or_else(invalid)?;
    // Freeze exactly the native committed range, then verify its final boundary.
    let mut frozen = tempfile::tempfile()?;
    if std::io::copy(&mut File::open(p)?.take(size), &mut frozen)? != size {
        return Err(invalid());
    }
    frozen.seek(SeekFrom::Start(0))?;
    let mut r = Reader::new(BufReader::new(frozen), s.limit);
    let mut h = b::header(Agent::Fx, id);
    if let Some(cwd) = first["payload"]["workspace_root"]
        .as_str()
        .filter(|p| common::absolute(p))
    {
        h["cwd"] = json!(cwd);
    }
    if let Some(ts) = b::timestamp(&first["payload"]["created_at_ms"]) {
        h["startedAt"] = json!(ts);
    }
    crate::repository::capture(&mut h, Agent::Fx, &first["payload"]);
    s.session(id, &h)?;
    let mut seq = 0;
    let mut last = Value::Null;
    let mut replacement: Option<(Value, Vec<u8>, u64)> = None;
    while let Some(line) = r.read()? {
        let Line::Record(v) = line else {
            return Err(invalid());
        };
        if v["schema_version"] != 1
            || v["timestamp_ms"].as_i64().is_none_or(|v| v < 0)
            || v["seq"].as_u64() != Some(seq + 1)
            || v["log_generation"] != generation
            || !hex(&v["event_id"], 32)
        {
            return Err(invalid());
        }
        seq += 1;
        last = v["event_id"].clone();
        let payload = &v["payload"];
        match v["kind"].as_str() {
            Some("state_replacement_started") => {
                if replacement.is_some()
                    || !hex(&payload["replacement_id"], 32)
                    || !hex(&payload["sha256"], 64)
                    || payload["encoded_bytes"]
                        .as_u64()
                        .is_none_or(|v| v > s.limit as u64)
                {
                    return Err(invalid());
                }
                replacement = Some((payload.clone(), Vec::new(), 0));
                b::push(s, id, v.clone(), n)?;
            }
            Some("state_replacement_chunk") => {
                let Some((start, data, index)) = replacement.as_mut() else {
                    return Err(invalid());
                };
                if payload["replacement_id"] != start["replacement_id"]
                    || payload["chunk_index"].as_u64() != Some(*index)
                {
                    return Err(invalid());
                }
                let bytes = STANDARD
                    .decode(payload["base64"].as_str().ok_or_else(invalid)?)
                    .map_err(|_| invalid())?;
                if payload["raw_bytes"].as_u64() != Some(bytes.len() as u64)
                    || payload["chunk_sha256"] != format!("{:x}", Sha256::digest(&bytes))
                    || data.len().saturating_add(bytes.len()) > s.limit
                {
                    return Err(invalid());
                }
                data.extend(bytes);
                *index += 1;
                // Encoded content bypasses ordinary secret filtering. Export only
                // the digest and byte counts. Decoded state is filtered separately.
                let mut retained = v.clone();
                retained["payload"]
                    .as_object_mut()
                    .unwrap()
                    .remove("base64");
                b::push(s, id, retained, n)?;
            }
            Some("state_replacement_committed") => {
                let Some((start, data, chunks)) = replacement.take() else {
                    return Err(invalid());
                };
                for key in ["replacement_id", "sha256", "encoded_bytes", "chunk_count"] {
                    if payload[key] != start[key] {
                        return Err(invalid());
                    }
                }
                if start["chunk_count"].as_u64() != Some(chunks)
                    || start["encoded_bytes"].as_u64() != Some(data.len() as u64)
                    || start["sha256"] != format!("{:x}", Sha256::digest(&data))
                {
                    return Err(invalid());
                }
                let state =
                    asr_core::jsonl::decode(std::str::from_utf8(&data).map_err(|_| invalid())?)?;
                if state["id"] != id {
                    return Err(invalid());
                }
                b::push(
                    s,
                    id,
                    json!({"_fxReplacement":state,"timestamp_ms":v["timestamp_ms"]}),
                    n,
                )?;
                b::push(s, id, v.clone(), n)?;
            }
            Some(_) if replacement.is_some() => return Err(invalid()),
            Some(_) => b::push(s, id, v.clone(), n)?,
            None => return Err(invalid()),
        }
    }
    if seq != through || last != wm["through_event_id"] || replacement.is_some() || r.bytes != size
    {
        return Err(invalid());
    }
    if b::document(&dir.join("authority.json"), s.limit)? != a
        || b::document(&wm_path, s.limit)? != wm
    {
        return Err(invalid());
    }
    for pending in ["authority.pending.json", "commit.pending.json"] {
        if dir.join(pending).exists() {
            return Err(invalid());
        }
    }
    n.source_bytes += size;
    n.files += 1;
    b::push(s, id, json!({"_fxAuthority":a,"watermark":wm}), n)
}
pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    b::time(c, &v["timestamp_ms"]);
    if let Some(state) = v.get("_fxReplacement") {
        let source = c.source.clone();
        c.loss("replacement_encoding");
        for (index, t) in state["history"]
            .as_array()
            .into_iter()
            .flatten()
            .enumerate()
        {
            let key = format!("fx-history:{index}");
            let digest = json!(format!("{:x}", Sha256::digest(t.to_string().as_bytes())));
            if s.entity(&key)?.as_ref() != Some(&digest) {
                turn(s, c, t)?;
                s.save(&key, &digest)?;
            }
        }
        s.save(
            "fx-history-count",
            &json!(state["history"].as_array().map_or(0, Vec::len)),
        )?;
        c.source = source;
        return c.vendor(s, v);
    }
    match v["kind"].as_str() {
        Some("state_replacement_chunk") => {
            c.loss("replacement_encoding");
            return c.emit(s,json!({"type":format!("{}/event",c.agent.domain()),"truncated":true,"_meta":{c.agent.domain():{"native":v}}}),None,None);
        }
        Some("session_started" | "preferences_changed") => {
            let p = if v["kind"] == "session_started" {
                &v["payload"]["preferences"]
            } else {
                &v["payload"]
            };
            let mut settings = json!({});
            if let Some(effort) = p.get("effort") {
                settings["modelSettings"] = json!({"reasoningEffort":effort});
            }
            c.settings(s, settings)?;
        }
        Some("history_turn_committed") => {
            let t = &v["payload"]["turn"];
            let count = s
                .entity("fx-history-count")?
                .and_then(|v| v.as_u64())
                .unwrap_or(0);
            let source = c.source.clone();
            turn(s, c, t)?;
            c.source = source;
            s.save(
                &format!("fx-history:{count}"),
                &json!(format!("{:x}", Sha256::digest(t.to_string().as_bytes()))),
            )?;
            s.save("fx-history-count", &json!(count + 1))?;
            totals(
                s,
                c,
                &v["payload"],
                "total_input_tokens",
                "total_output_tokens",
            )?;
        }
        Some("usage_checkpointed") => {
            totals(
                s,
                c,
                &v["payload"]["usage"],
                "input_tokens",
                "output_tokens",
            )?;
        }
        _ => {}
    }
    c.vendor(s, v)
}
fn totals(s: &Spool, c: &mut Context, v: &Value, _input: &str, output: &str) -> Result<()> {
    let mut usage = json!({});
    for (dst, src) in [
        ("outputTokens", output),
        ("cacheReadTokens", "cache_read_tokens"),
        ("cacheWriteTokens", "cache_write_tokens"),
    ] {
        if let Some(n) = b::count(&v[src]) {
            usage[dst] = json!(n);
        }
    }
    if !usage.as_object().unwrap().is_empty() {
        c.info(s, json!({"type":"session_info","usage":usage}))?;
    }
    Ok(())
}
fn message(s: &Spool, c: &mut Context, role: &str, v: &Value, interrupted: bool) -> Result<()> {
    if let Some(text) = v.as_str() {
        let mut r = json!({"type":"message","role":role,"content":[common::text(text)]});
        if role == "assistant" {
            r["author"] = json!("model");
            if interrupted {
                r["status"] = json!("interrupted");
            }
        }
        c.emit(s, r, None, None)?;
    } else if !v.is_null() {
        c.loss("non_utf8_content");
    }
    Ok(())
}
fn tool(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    b::call(
        s,
        c,
        v,
        v["id"].as_str(),
        v["name"].as_str(),
        v.get("arguments_json"),
        None,
    )?;
    Ok(())
}
fn turn(s: &Spool, c: &mut Context, t: &Value) -> Result<()> {
    // Turn snapshots have no per-item timestamps. Do not borrow the commit time.
    c.source.as_object_mut().unwrap().remove("ts");
    if t["kind"] == "compacted_summary" {
        c.emit(s,json!({"type":"message","role":"user","author":"harness","origin":"compaction","content":common::parts(&t["summary"],c.agent)}),None,None)?;
        c.emit(s,json!({"type":"gap","reason":"not_retained","detail":"Native replacement includes a compacted history summary."}),None,None)?;
        return Ok(());
    }
    message(s, c, "user", &t["user"]["text"], false)?;
    for step in t["execution"]["tool_steps"]
        .as_array()
        .into_iter()
        .flatten()
    {
        message(s, c, "assistant", &step["assistant"], false)?;
        for call in step["tool_calls"].as_array().into_iter().flatten() {
            tool(s, c, call)?;
        }
        for result in step["tool_results"].as_array().into_iter().flatten() {
            let mut r = json!({"type":"tool_result","status":match result["status"].as_str(){Some("success")=>"completed",Some("failure")=>"failed",_=>"unknown"}});
            if let Some(id) = result["tool_call_id"].as_str() {
                r["callId"] = json!(id);
            }
            if result["output"].is_string() {
                r["content"] = json!(common::parts(&result["output"], c.agent));
            }
            if result["truncated"] == true {
                r["truncated"] = json!(true);
                c.loss("tool_output");
            }
            if let Some(ts) = b::timestamp(&result["created_at_ms"]) {
                r["ts"] = json!(ts);
            }
            let process = &result["command_process_presentation"];
            if process["kind"] == "exit_code" && process["value"].is_i64() {
                r["exec"] = json!({"exitCode":process["value"]});
            }
            c.result(s, r)?;
        }
    }
    if t["tool_call"].is_object() {
        tool(s, c, &t["tool_call"])?;
    }
    message(
        s,
        c,
        "assistant",
        &t["assistant"],
        t["kind"] == "interrupted",
    )?;
    for f in t["execution"]["files"].as_array().into_iter().flatten() {
        let Some(path) = f["path"].as_str() else {
            continue;
        };
        let op = match f["action"].as_str() {
            Some("write" | "edit") => "modify",
            Some("delete") => "delete",
            Some("rename") => "move",
            Some("copy") => "copy",
            _ => continue,
        };
        let mut r = json!({"type":"file_change","path":common::path(path,c.cwd.as_deref()),"op":op,"status":match f["status"].as_str(){Some("success")=>"applied",Some("failure")=>"failed",_=>"unknown"}});
        if matches!(op, "move" | "copy") {
            let Some(new) = f["new_path"].as_str() else {
                continue;
            };
            r["oldPath"] = r["path"].clone();
            r["path"] = json!(common::path(new, c.cwd.as_deref()));
        }
        if let Some(id) = f["tool_call_id"].as_str() {
            r["callId"] = json!(id);
        }
        c.emit(s, r, None, None)?;
    }
    Ok(())
}
