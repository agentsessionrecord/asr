//! Legacy Vibe transcripts and immutable unified-store generations.
use crate::{
    batch_a as b,
    common::{self, Context},
    spool::Spool,
    Agent, Error, Result, Summary,
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::path::{Component, Path, PathBuf};

pub fn stage(s: &mut Spool, p: &Path, n: &mut Summary) -> Result<()> {
    let meta_path = p.with_file_name("meta.json");
    if !meta_path.is_file() {
        n.files += 1;
        n.diagnostic("unidentified_source");
        return Ok(());
    }
    let meta = b::document(&meta_path, s.limit)?;
    let Some(id) = b::nonempty(&meta["session_id"]) else {
        n.files += 1;
        n.diagnostic("unidentified_source");
        return Ok(());
    };
    let mut h = b::header(Agent::MistralVibe, id);
    if let Some(ts) = b::timestamp(&meta["start_time"]) {
        h["startedAt"] = json!(ts);
    }
    if let Some(cwd) = meta
        .pointer("/environment/working_directory")
        .and_then(Value::as_str)
        .filter(|p| common::absolute(p))
    {
        h["cwd"] = json!(cwd);
    }
    crate::repository::capture(&mut h, Agent::MistralVibe, &meta);
    // A parent ID alone does not distinguish a spawn, fork or continuation.
    s.session(id, &h)?;
    b::lines(s, p, id, n)?;
    b::push(s, id, json!({"_vibeMetadata":meta}), n)
}
pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if b::gap(s, c, v)? {
        return Ok(());
    }
    if let Some(meta) = v.get("_vibeMetadata") {
        let mut info = json!({"type":"session_info"});
        if let Some(title) = meta["title"].as_str() {
            info["title"] = json!(title);
        }
        if let Some(ts) = b::timestamp(&meta["end_time"]) {
            info["endedAt"] = json!(ts);
        }
        let mut usage = json!({});
        for (dst, src) in [
            ("outputTokens", "session_completion_tokens"),
            ("cacheReadTokens", "session_cached_tokens"),
        ] {
            if let Some(n) = b::count(&meta["stats"][src]) {
                usage[dst] = json!(n);
            }
        }
        if !usage.as_object().unwrap().is_empty() {
            info["usage"] = usage;
        }
        if meta["stats"]["session_cost"].is_number() {
            info["cost"] = json!({"amount":meta["stats"]["session_cost"],"currency":"USD","source":"harness_estimated"});
        }
        if info.as_object().unwrap().len() > 1 {
            c.info(s, info)?;
        }
        return c.vendor(s, v);
    }
    if let Some(m) = v.get("_vibeMessage") {
        return unified_message(s, c, m);
    }
    if v.get("_vibeComponent").is_some() {
        c.loss("recovery_projection");
        return c.vendor(s, v);
    }
    b::time(c, &v["timestamp"]);
    let Some(role) = v["role"]
        .as_str()
        .filter(|v| matches!(*v, "user" | "assistant" | "system" | "developer" | "tool"))
    else {
        return c.vendor(s, v);
    };
    if role == "tool" {
        let mut r = json!({"type":"tool_result","status":if v["tool_result"]["cancelled"]==true{"cancelled"}else{"unknown"}});
        if let Some(id) = v["tool_call_id"].as_str() {
            r["callId"] = json!(id);
        }
        if let Some(content) = v.get("content").filter(|v| !v.is_null()) {
            r["content"] = json!(common::parts(content, c.agent));
        }
        if let Some(sec) = v["tool_result"]["duration"]
            .as_f64()
            .filter(|v| *v >= 0.0 && v.is_finite())
        {
            r["durationMs"] = json!(sec * 1000.0);
        }
        c.result(s, r)?;
        return c.vendor(s, v);
    }
    let mut content = common::parts(&v["content"], c.agent);
    if let Some(reason) = v["reasoning_content"].as_str() {
        content.push(common::reasoning(Some(reason), None));
    }
    for img in v["images"].as_array().into_iter().flatten() {
        content.push(b::vendor_part(c.agent, img));
    }
    let mut r = json!({"type":"message","role":role,"content":content});
    if role == "assistant" {
        r["author"] = json!("model");
    }
    if v["injected"] == true {
        r["author"] = json!("harness");
        r["origin"] = json!("injected");
    }
    if v["context_boundary"] == "compaction" {
        r["author"] = json!("harness");
        r["origin"] = json!("compaction");
    }
    if v.get("content").is_some_and(|v| !v.is_null())
        || !r["content"].as_array().unwrap().is_empty()
    {
        c.emit(s, r, v["message_id"].as_str(), None)?;
    } else {
        c.loss("message_content");
    }
    if v["context_boundary"] == "compaction" {
        c.emit(s,json!({"type":"gap","reason":"not_retained","detail":"Native compaction removed earlier context."}),None,None)?;
    }
    for call in v["tool_calls"].as_array().into_iter().flatten() {
        b::call(
            s,
            c,
            call,
            call["id"].as_str(),
            call["function"]["name"].as_str(),
            call["function"].get("arguments"),
            None,
        )?;
    }
    if let Some(shell) = v.get("manual_shell") {
        let id = shell["operation_id"]
            .as_str()
            .map(str::to_owned)
            .unwrap_or_else(|| {
                asr_core::identity::derive_id(&[&c.session, &c.pos.to_string(), "shell"])
            });
        let mut call =
            json!({"type":"tool_call","callId":id,"kind":"execute","requestedBy":"user"});
        if let Some(command) = shell.get("command") {
            call["input"] = json!({"command":command});
        }
        c.emit(s, call, None, None)?;
        let mut r = json!({"type":"tool_result","callId":id,"status":if shell["interrupted"]==true{"interrupted"}else{"unknown"}});
        let mut exec = json!({});
        for (dst, src) in [
            ("command", "command"),
            ("stdout", "stdout"),
            ("stderr", "stderr"),
            ("output", "output_text"),
        ] {
            common::copy(&mut exec, dst, shell, src);
        }
        if let Some(code) = shell["exit_code"]
            .as_i64()
            .filter(|v| v.abs() <= 9_007_199_254_740_991)
        {
            exec["exitCode"] = json!(code);
        }
        if let Some(cwd) = shell["cwd"].as_str().filter(|p| common::absolute(p)) {
            exec["cwd"] = json!(cwd);
        }
        if !exec.as_object().unwrap().is_empty() {
            r["exec"] = exec;
        }
        if shell["duration_ms"].is_number() {
            r["durationMs"] = shell["duration_ms"].clone();
        }
        c.result(s, r)?;
    }
    c.vendor(s, v)
}
fn child(root: &Path, name: &str) -> Result<PathBuf> {
    if name.is_empty()
        || Path::new(name)
            .components()
            .any(|v| !matches!(v, Component::Normal(_)))
    {
        return Err(Error::Invalid("invalid native store path".into()));
    }
    let path = root.join(name);
    if !std::fs::canonicalize(&path)?.starts_with(std::fs::canonicalize(root)?) {
        return Err(Error::Invalid("native store path escapes root".into()));
    }
    Ok(path)
}
fn checked(root: &Path, desc: &Value, limit: usize) -> Result<Value> {
    let path = child(
        root,
        desc["path"]
            .as_str()
            .ok_or_else(|| Error::Invalid("missing native component path".into()))?,
    )?;
    use std::io::Read;
    let mut data = Vec::new();
    std::fs::File::open(&path)?
        .take(limit as u64 + 1)
        .read_to_end(&mut data)?;
    if data.len() > limit {
        return Err(Error::Invalid(
            "native component exceeded record bound".into(),
        ));
    }
    let bytes = data.strip_suffix(b"\n").unwrap_or(&data);
    if desc["sha256"]
        .as_str()
        .is_none_or(|hash| format!("{:x}", Sha256::digest(bytes)) != hash)
    {
        return Err(Error::Invalid("native component digest mismatch".into()));
    }
    b::document(&path, limit)
}
pub fn unified(s: &mut Spool, root: &Path, n: &mut Summary) -> Result<()> {
    let current = b::document(&root.join("CURRENT"), s.limit)?;
    if current["store_format"] != "mistral.vibe.unified-session-store/v1"
        || current["store_format_minor"]
            .as_u64()
            .is_none_or(|v| v > 10)
    {
        return Err(Error::Invalid("unsupported Vibe store version".into()));
    }
    let id = b::nonempty(&current["session_id"])
        .ok_or_else(|| Error::Invalid("missing Vibe session identity".into()))?;
    let gen = current["generation"]
        .as_str()
        .ok_or_else(|| Error::Invalid("missing Vibe generation".into()))?;
    let dir = child(root, &format!("generations/{gen}"))?;
    let manifest = checked(
        &dir,
        &json!({"path":"manifest.json","sha256":current["manifest_sha256"]}),
        s.limit,
    )?;
    for field in ["session_id", "generation", "snapshot_sequence"] {
        if manifest[field] != current[field] {
            return Err(Error::Invalid(
                "inconsistent Vibe generation identity".into(),
            ));
        }
    }
    let runtime = checked(&dir, &manifest["runtime_state"], s.limit)?;
    let mut h = b::header(Agent::MistralVibe, id);
    h["producer"]["source"] = json!("mistral.vibe.unified-session-store/v1");
    if let Some(cwd) = runtime["session_metadata"]["cwd"]
        .as_str()
        .filter(|p| common::absolute(p))
    {
        h["cwd"] = json!(cwd);
    }
    crate::repository::capture(&mut h, Agent::MistralVibe, &runtime["session_metadata"]);
    s.session(id, &h)?;
    for (field, pointer) in [
        ("checkpoint", "/context/messages"),
        ("runtime_state", ""),
        ("projection_state", "/snapshot/history/entries"),
    ] {
        let v = checked(&dir, &manifest[field], s.limit)?;
        n.source_bytes +=
            std::fs::metadata(child(&dir, manifest[field]["path"].as_str().unwrap())?)?.len();
        if field == "checkpoint" {
            for m in v
                .pointer(pointer)
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
            {
                b::push(s, id, json!({"_vibeMessage":m}), n)?;
            }
        } else {
            b::push(s, id, json!({"_vibeComponent":field,"value":v}), n)?;
        }
        for hash in manifest[field]["chunks"].as_array().into_iter().flatten() {
            let hash = hash
                .as_str()
                .filter(|s| s.len() == 64 && s.bytes().all(|b| b.is_ascii_hexdigit()))
                .ok_or_else(|| Error::Invalid("invalid Vibe chunk digest".into()))?;
            let chunk = checked(
                root,
                &json!({"path":format!("chunks/{hash}.json"),"sha256":hash}),
                s.limit,
            )?;
            for m in chunk.as_array().into_iter().flatten() {
                b::push(
                    s,
                    id,
                    if field == "checkpoint" {
                        json!({"_vibeMessage":m})
                    } else {
                        json!({"_vibeComponent":field,"value":m})
                    },
                    n,
                )?;
            }
        }
    }
    let journal = child(
        root,
        manifest["recovery_journal_segment"]["path"]
            .as_str()
            .unwrap_or("journal"),
    )?;
    // Recovery observations are not replayed as model actions without a complete
    // reducer. Retain them as vendor evidence and declare the projection loss.
    let mut r = asr_core::jsonl::Reader::new(b::reader(&journal)?, s.limit);
    while let Some(line) = r.read()? {
        match line {
            asr_core::jsonl::Line::Record(v) => {
                b::push(s, id, json!({"_vibeComponent":"recovery","value":v}), n)?
            }
            asr_core::jsonl::Line::Incomplete => n.diagnostic("incomplete_source_tail"),
            _ => return Err(Error::Invalid("invalid Vibe recovery journal".into())),
        }
    }
    n.source_bytes += r.bytes;
    n.files += 1;
    if b::document(&root.join("CURRENT"), s.limit)? != current {
        return Err(Error::Invalid(
            "Vibe generation changed during capture".into(),
        ));
    }
    b::push(
        s,
        id,
        json!({"_vibeComponent":"manifest","value":manifest}),
        n,
    )
}
fn unified_message(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    c.loss("recovery_projection");
    let m = &v["message"];
    let role = m["role"].as_str().unwrap_or_default();
    if role == "tool" {
        let mut r = json!({"type":"tool_result","status":match m["outcome"].as_str(){Some("success")=>"completed",Some("error")=>"failed",_=>"unknown"},"_meta":{c.agent.domain():{"native":v}}});
        if let Some(id) = m["tool_call_id"].as_str() {
            r["callId"] = json!(id);
        }
        c.loss("tool_output");
        return c.result(s, r);
    }
    if !matches!(role, "system" | "user" | "assistant" | "developer") {
        return c.vendor(s, v);
    }
    let body: Vec<_> = m["content"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|p| p["type"] != "tool_call")
        .cloned()
        .collect();
    let mut r = json!({"type":"message","role":role,"content":common::parts(&json!(body),c.agent)});
    if role == "assistant" {
        r["author"] = json!("model");
    }
    c.emit(s, r, None, None)?;
    for p in m["content"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|p| p["type"] == "tool_call")
    {
        b::call(
            s,
            c,
            p,
            p["id"].as_str(),
            p["name"].as_str(),
            p["arguments"].get("raw").or(p["arguments"].get("value")),
            None,
        )?;
    }
    c.vendor(s, v)
}
