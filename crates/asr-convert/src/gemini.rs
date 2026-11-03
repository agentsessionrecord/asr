//! Gemini CLI chat journals and legacy recording snapshots.
use crate::{
    batch_a as b,
    common::{self, Context},
    spool::Spool,
    Agent, Result, Summary,
};
use asr_core::{
    identity::derive_id,
    jsonl::{Line, Reader},
};
use serde_json::{json, Value};
use std::path::Path;

pub fn stage(s: &mut Spool, p: &Path, n: &mut Summary) -> Result<()> {
    let legacy = p.extension().is_some_and(|v| v == "json");
    let mut first = None;
    let mut ambiguous = false;
    if legacy {
        let v = b::document(p, s.limit)?;
        if b::nonempty(&v["sessionId"]).is_some() {
            first = Some(v);
        }
    } else {
        let mut r = Reader::new(b::reader(p)?, s.limit);
        while let Some(line) = r.read()? {
            if let Line::Record(v) = line {
                let meta = v.get("$set").unwrap_or(&v);
                if let Some(id) = b::nonempty(&meta["sessionId"]) {
                    if first.as_ref().is_some_and(|v: &Value| v["sessionId"] != id) {
                        ambiguous = true;
                    }
                    if first.is_none() {
                        first = Some(meta.clone());
                    }
                }
            }
        }
    }
    let Some(first) = first.filter(|_| !ambiguous) else {
        n.files += 1;
        n.diagnostic("unidentified_source");
        return Ok(());
    };
    let id = first["sessionId"].as_str().unwrap();
    let mut h = b::header(Agent::GeminiCli, id);
    crate::repository::capture(&mut h, Agent::GeminiCli, &first);
    if legacy {
        h["producer"]["source"] = json!("gemini-cli-chat-recording");
    }
    if let Some(start) = b::timestamp(&first["startTime"]) {
        h["startedAt"] = json!(start);
    }
    if first["kind"] == "subagent" {
        if let Some(parent) = p
            .parent()
            .filter(|p| p.parent().is_some_and(|p| p.ends_with("chats")))
            .and_then(Path::file_name)
            .and_then(|v| v.to_str())
            .filter(|v| *v != id)
        {
            h["parent"] = json!({"kind":"subagent","session":asr_core::identity::session_ref(Agent::GeminiCli.name(),None,parent)});
        }
    }
    s.session(id, &h)?;
    if legacy {
        n.files += 1;
        n.source_bytes += std::fs::metadata(p)?.len();
        b::push(s, id, json!({"$set":first}), n)
    } else {
        b::lines(s, p, id, n)
    }
}
pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if b::gap(s, c, v)? {
        return Ok(());
    }
    b::time(c, &v["timestamp"]);
    let source = c.source.clone();
    if v.get("$rewindTo").is_some() {
        return c.vendor(s, v);
    }
    if let Some(set) = v.get("$set") {
        if let Some(messages) = set["messages"].as_array() {
            // Earlier observed work stays in the stream. A snapshot may omit work
            // that was already lost before capture and cannot restore that evidence.
            c.loss("snapshot_history");
            for m in messages {
                message(s, c, m)?;
            }
            c.source = source.clone();
            c.emit(s,json!({"type":"gap","reason":"not_retained","detail":"Native history snapshot may omit earlier work."}),None,None)?;
        }
        if let Some(title) = set["summary"].as_str() {
            c.info(s, json!({"type":"session_info","title":title}))?;
        }
    } else if let Some(m) = v.get("pushMessage") {
        message(s, c, m)?;
    } else if v["id"].is_string() {
        message(s, c, v)?;
    }
    c.source = source;
    c.vendor(s, v)
}
fn parts(v: &Value, a: Agent) -> Vec<Value> {
    let items = v
        .as_array()
        .map(Vec::as_slice)
        .unwrap_or_else(|| std::slice::from_ref(v));
    items.iter().filter_map(|p| {
        if p.is_null() || p.get("functionCall").is_some() || p.get("functionResponse").is_some() {return None;}
        Some(if let Some(text) = p.as_str().or(p["text"].as_str()) {
            if p["thought"] == true {json!({"type":"reasoning","visibility":"summary","summary":[text]})} else {common::text(text)}
        } else if p.get("thoughtSignature").is_some() {json!({"type":"reasoning","visibility":"omitted"})}
        else if let Some(mime) = p["inlineData"]["mimeType"].as_str().filter(|s| s.starts_with("image/") || s.starts_with("audio/")) {
            let mut part = json!({"type":if mime.starts_with("image/"){"image"}else{"audio"},"mimeType":mime});
            if let Some(data) = p["inlineData"]["data"].as_str() {part["data"] = json!(data);}
            part
        } else if let Some(uri) = p["fileData"]["fileUri"].as_str() {json!({"type":"resource_link","uri":uri,"name":uri})}
        else {b::vendor_part(a,p)})
    }).collect()
}
fn message(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    let Some(role) = (match v["type"].as_str() {
        Some("gemini") => Some("assistant"),
        Some("user") => Some("user"),
        _ => None,
    }) else {
        return c.vendor(s, v);
    };
    b::time(c, &v["timestamp"]);
    let id = v["id"].as_str().map(str::to_owned).unwrap_or_else(|| {
        derive_id(&[
            &c.session,
            &c.pos.to_string(),
            &c.slot.to_string(),
            "message",
        ])
    });
    let inference = derive_id(&[&id, "inference"]);
    let has_inference = role == "assistant" && v["tokens"].is_object();
    let mut content = parts(&v["content"], c.agent);
    for t in v["thoughts"].as_array().into_iter().flatten() {
        if let Some(text) = t["description"].as_str() {
            content.push(json!({"type":"reasoning","visibility":"summary","summary":[text]}));
        }
    }
    let mut m = json!({"type":"message","role":role,"content":content});
    if role == "assistant" {
        m["author"] = json!("model");
    }
    if has_inference {
        m["inferenceId"] = json!(inference);
    }
    if v.get("content").is_some_and(|v| !v.is_null())
        || !m["content"].as_array().unwrap().is_empty()
    {
        c.emit(s, m, Some(&id), Some(&format!("gemini-message:{id}")))?;
    } else {
        c.loss("message_content");
    }
    for (i, tc) in v["toolCalls"].as_array().into_iter().flatten().enumerate() {
        let cid = tc["id"]
            .as_str()
            .map(str::to_owned)
            .unwrap_or_else(|| derive_id(&[&id, &i.to_string(), "tool"]));
        call(
            s,
            c,
            tc,
            &cid,
            has_inference.then_some(inference.as_str()),
            &id,
        )?;
        if tc.get("result").is_some_and(|v| !v.is_null())
            || matches!(
                tc["status"].as_str(),
                Some("success" | "error" | "cancelled")
            )
        {
            result(s, c, Some(&cid), tc.get("result"), tc)?;
            file_change(s, c, &cid, tc)?;
        }
    }
    for (i, p) in v["content"].as_array().into_iter().flatten().enumerate() {
        if let Some(fc) = p.get("functionCall") {
            let cid = fc["id"]
                .as_str()
                .map(str::to_owned)
                .unwrap_or_else(|| derive_id(&[&id, &i.to_string(), "function"]));
            if !v["toolCalls"]
                .as_array()
                .into_iter()
                .flatten()
                .any(|tc| tc["id"] == cid)
            {
                call(
                    s,
                    c,
                    fc,
                    &cid,
                    has_inference.then_some(inference.as_str()),
                    &id,
                )?;
            }
        }
        if let Some(fr) = p.get("functionResponse") {
            result(s, c, fr["id"].as_str(), Some(&json!([p])), &json!({}))?;
        }
    }
    if has_inference {
        let t = &v["tokens"];
        let mut usage = json!({});
        for (dst, src) in [
            ("inputTokens", "input"),
            ("cacheReadTokens", "cached"),
            ("reasoningTokens", "thoughts"),
        ] {
            if let Some(n) = b::count(&t[src]) {
                usage[dst] = json!(n);
            }
        }
        let thoughts = if t.get("thoughts").is_none() {
            Some(0)
        } else {
            b::count(&t["thoughts"])
        };
        if let Some(out) = b::count(&t["output"])
            .and_then(|n| thoughts.and_then(|thoughts| n.checked_add(thoughts)))
            .filter(|v| *v <= 9_007_199_254_740_991)
        {
            usage["outputTokens"] = json!(out);
        }
        let mut r =
            json!({"type":"inference","usage":usage,"_meta":{c.agent.domain():{"tokens":t}}});
        if let Some(model) = b::nonempty(&v["model"]) {
            r["model"] = json!({"requested":model});
        }
        c.emit(
            s,
            r,
            Some(&inference),
            Some(&format!("inference:{inference}")),
        )?;
    }
    Ok(())
}
fn call(
    s: &Spool,
    c: &mut Context,
    v: &Value,
    id: &str,
    inference: Option<&str>,
    owner: &str,
) -> Result<()> {
    let mut r = json!({"type":"tool_call","callId":id,"requestedBy":"model"});
    if let Some(name) = v["name"].as_str() {
        r["name"] = json!(name);
        if let Some(kind) = match name {
            "replace" | "write_file" => Some("edit"),
            "read_file" => Some("read"),
            "run_shell_command" => Some("execute"),
            _ => None,
        } {
            r["kind"] = json!(kind);
        }
    }
    if let Some(input) = v.get("args") {
        r["input"] = input.clone();
    }
    if let Some(inference) = inference {
        r["inferenceId"] = json!(inference);
    }
    c.emit(s, r, None, Some(&format!("gemini-call:{owner}:{id}")))
}
fn result(
    s: &Spool,
    c: &mut Context,
    id: Option<&str>,
    value: Option<&Value>,
    native: &Value,
) -> Result<()> {
    let mut r = json!({"type":"tool_result","status":match native["status"].as_str(){Some("success")=>"completed",Some("error")=>"failed",Some("cancelled")=>"cancelled",_=>"unknown"}});
    if let Some(id) = id {
        r["callId"] = json!(id);
        if native.get("status").is_none() {
            if let Some(previous) = s.entity(&format!("gemini-result-status:{id}"))? {
                r["status"] = previous;
            }
        } else {
            s.save(&format!("gemini-result-status:{id}"), &r["status"])?;
        }
    }
    if let Some(value) = value.filter(|v| !v.is_null()) {
        let mut content = Vec::new();
        for p in value
            .as_array()
            .map(Vec::as_slice)
            .unwrap_or_else(|| std::slice::from_ref(value))
        {
            if let Some(response) = p.pointer("/functionResponse/response") {
                if let Some(out) = response["output"].as_str() {
                    if out.starts_with("<tool_output_masked>")
                        && out.ends_with("</tool_output_masked>")
                    {
                        r["truncated"] = json!(true);
                        c.loss("tool_output");
                    }
                    content.push(common::text(out));
                } else {
                    content.push(b::vendor_part(c.agent, response));
                }
            } else {
                content.extend(parts(p, c.agent));
            }
        }
        r["content"] = json!(content);
    }
    // A missing native result time stays unknown, even inside a timed message.
    let previous = c.source.as_object_mut().unwrap().remove("ts");
    if let Some(ts) = b::timestamp(&native["timestamp"]) {
        r["ts"] = json!(ts);
    }
    c.result(s, r)?;
    if let Some(ts) = previous {
        c.source["ts"] = ts;
    }
    Ok(())
}
fn file_change(s: &Spool, c: &mut Context, id: &str, tc: &Value) -> Result<()> {
    if !matches!(tc["name"].as_str(), Some("replace" | "write_file")) {
        return Ok(());
    }
    let d = &tc["resultDisplay"];
    let Some(path) = d["filePath"].as_str() else {
        return Ok(());
    };
    let mut r = json!({"type":"file_change","callId":id,"path":common::path(path,c.cwd.as_deref()),"op":match d["isNewFile"].as_bool(){Some(true)=>"add",Some(false)=>"modify",None=>"unknown"},"status":match tc["status"].as_str(){Some("success")=>"applied",Some("error")=>"failed",_=>"unknown"}});
    if let Some(patch) = d["fileDiff"].as_str() {
        r["patch"] = json!(patch);
    }
    if let Some(after) = d["newContent"].as_str() {
        r["after"] = json!({"text":after});
    }
    // A failed read's empty fallback is not evidence of an empty original file.
    if d["isNewFile"] == false {
        if let Some(before) = d["originalContent"].as_str().filter(|v| !v.is_empty()) {
            r["before"] = json!({"text":before});
        }
    }
    c.emit(s, r, None, Some(&format!("gemini-file:{id}:{path}")))
}
