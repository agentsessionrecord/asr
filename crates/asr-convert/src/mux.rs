//! Mux message snapshots and staged partial selection.
use crate::{
    batch_a as b,
    common::{self, Context},
    spool::Spool,
    Agent, Result, Summary,
};
use serde_json::{json, Value};
use std::path::Path;

pub fn stage(s: &mut Spool, p: &Path, n: &mut Summary) -> Result<()> {
    let dir = p.parent().unwrap();
    let companion = |name: &str| {
        [
            name.to_owned(),
            format!("{name}.zst"),
            format!("{name}.zstd"),
        ]
        .into_iter()
        .map(|v| dir.join(v))
        .find(|p| p.is_file())
    };
    let active = companion("chat.jsonl");
    let archive = companion("chat-archive.jsonl");
    let partial = dir.join("partial.json");
    let selected = active.as_deref().or(archive.as_deref()).unwrap_or(&partial);
    // Active and archive are ingested together exactly once.
    if p != selected {
        return Ok(());
    }
    let meta = if dir.join("metadata.json").is_file() {
        b::document(&dir.join("metadata.json"), s.limit)?
    } else {
        json!({})
    };
    let partial_value = partial
        .is_file()
        .then(|| b::document(&partial, s.limit))
        .transpose()?;
    let mut recorded = None;
    let mut ambiguous = false;
    let mut observe_identity = |v: &Value| {
        if let Some(id) = b::nonempty(&v["workspaceId"]) {
            ambiguous |= recorded.as_deref().is_some_and(|old| old != id);
            recorded = Some(id.to_owned());
        }
    };
    observe_identity(&meta);
    if let Some(value) = &partial_value {
        observe_identity(value);
    }
    for source in archive.iter().chain(active.iter()) {
        let mut input = asr_core::jsonl::Reader::new(b::reader(source)?, s.limit);
        while let Some(line) = input.read()? {
            if let asr_core::jsonl::Line::Record(v) = line {
                observe_identity(&v);
            }
        }
    }
    if ambiguous {
        n.files += 1;
        n.diagnostic("ambiguous_source_identity");
        return Ok(());
    }
    // The native sessions/<workspaceId> storage key is also an identity source.
    let id = recorded.or_else(|| {
        dir.parent()
            .filter(|p| p.ends_with("sessions") || p.ends_with("subagent-transcripts"))
            .and_then(|_| dir.file_name()?.to_str().map(str::to_owned))
    });
    let Some(id) = id else {
        n.files += 1;
        n.diagnostic("unidentified_source");
        return Ok(());
    };
    let mut h = b::header(Agent::Mux, &id);
    if let Some(cwd) = meta["projectPath"].as_str().filter(|p| common::absolute(p)) {
        h["cwd"] = json!(cwd);
    }
    crate::repository::capture(&mut h, Agent::Mux, &meta);
    s.session(&id, &h)?;
    if let Some(archive) = archive.as_ref().filter(|path| path.as_path() != p) {
        b::lines(s, archive, &id, n)?;
    }
    if p.file_name().is_none_or(|v| v != "partial.json") {
        b::lines(s, p, &id, n)?;
    }
    if let Some(value) = partial_value {
        b::push(s, &id, json!({"_muxPartial":value}), n)?;
        n.source_bytes += std::fs::metadata(&partial)?.len();
        if p == partial {
            n.files += 1;
        }
    }
    if !meta.as_object().is_none_or(|m| m.is_empty()) {
        b::push(s, &id, json!({"_muxMetadata":meta}), n)?;
    }
    let index = dir.join("subagent-transcripts.json");
    if index.is_file() {
        let v = b::document(&index, s.limit)?;
        b::push(s, &id, json!({"_muxArchiveIndex":v}), n)?;
    }
    Ok(())
}
fn partial_selected(s: &Spool, c: &Context, partial: &Value) -> Result<bool> {
    let Some(seq) = partial
        .pointer("/metadata/historySequence")
        .filter(|v| !v.is_null())
    else {
        return Ok(true);
    };
    let mut cursor = 0;
    while let Some((pos, v)) = s.next_native(&c.session, cursor)? {
        cursor = pos;
        if v.pointer("/metadata/historySequence") == Some(seq)
            && v["parts"].as_array().map_or(0, Vec::len)
                >= partial["parts"].as_array().map_or(0, Vec::len)
        {
            return Ok(false);
        }
    }
    Ok(true)
}
fn partial_state(s: &Spool, c: &Context) -> Result<Value> {
    if let Some(state) = s.entity("mux-partial-state")? {
        return Ok(state);
    }
    let mut cursor = 0;
    let mut state = json!({"selected":false});
    while let Some((pos, v)) = s.next_native(&c.session, cursor)? {
        cursor = pos;
        if let Some(partial) = v.get("_muxPartial") {
            state = json!({"selected":partial_selected(s,c,partial)?,"sequence":partial["metadata"]["historySequence"]});
        }
    }
    s.save("mux-partial-state", &state)?;
    Ok(state)
}
pub fn convert(s: &Spool, c: &mut Context, raw: &Value) -> Result<()> {
    if b::gap(s, c, raw)? {
        return Ok(());
    }
    if raw.get("_muxMetadata").is_some() {
        if let Some(name) = raw["_muxMetadata"]["name"].as_str() {
            c.info(s, json!({"type":"session_info","title":name}))?;
        }
        return c.vendor(s, raw);
    }
    if raw.get("_muxArchiveIndex").is_some() {
        return c.vendor(s, raw);
    }
    let state = partial_state(s, c)?;
    let v = if let Some(p) = raw.get("_muxPartial") {
        if state["selected"] != true {
            return c.vendor(s, raw);
        }
        p
    } else {
        if state["selected"] == true
            && !state["sequence"].is_null()
            && raw.pointer("/metadata/historySequence") == Some(&state["sequence"])
        {
            return c.vendor(s, raw);
        }
        raw
    };
    let Some(role) = v["role"]
        .as_str()
        .filter(|v| matches!(*v, "user" | "assistant" | "system" | "developer"))
    else {
        return c.vendor(s, raw);
    };
    if !v["parts"].is_array() {
        c.loss("message_content");
        return c.vendor(s, raw);
    }
    b::time(c, v.get("createdAt").unwrap_or(&v["metadata"]["timestamp"]));
    let mut body = Vec::new();
    for p in v["parts"].as_array().into_iter().flatten() {
        match p["type"].as_str() {
            Some("dynamic-tool") => {},
            Some("text") if p["text"].is_string() => body.push(common::text(p["text"].as_str().unwrap())),
            Some("reasoning") => body.push(common::reasoning(p["text"].as_str(), None)),
            Some("file") if p["url"].is_string() => body.push(json!({"type":"resource_link","uri":p["url"],"name":p["filename"].as_str().unwrap_or("attachment")})),
            _ => body.push(b::vendor_part(c.agent,p)),
        }
    }
    let mut r = json!({"type":"message","role":role,"content":body});
    if role == "assistant" {
        r["author"] = json!("model");
    }
    if v["metadata"]["compactionBoundary"] == true
        || v["metadata"]["compacted"] == true
        || matches!(v["metadata"]["compacted"].as_str(), Some("user" | "idle"))
    {
        r["author"] = json!("harness");
        r["origin"] = json!("compaction");
        c.loss("compaction_history");
        c.emit(s, r, v["id"].as_str(), None)?;
        c.emit(s,json!({"type":"gap","reason":"not_retained","detail":"Native compaction replaced earlier history."}),None,None)?;
    } else {
        c.emit(
            s,
            r,
            v["id"].as_str(),
            v["id"]
                .as_str()
                .map(|id| format!("mux-message:{id}"))
                .as_deref(),
        )?;
    }
    // Usage is accumulated across model steps, not one inference or a session total.
    if v["metadata"]["usage"].is_object() {
        c.loss("usage_scope");
    }
    for p in v["parts"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|p| p["type"] == "dynamic-tool")
    {
        tool(s, c, p, None)?;
        for nested in p["nestedCalls"].as_array().into_iter().flatten() {
            tool(s, c, nested, p["toolCallId"].as_str())?;
        }
    }
    c.vendor(s, raw)
}
fn tool(s: &Spool, c: &mut Context, p: &Value, parent: Option<&str>) -> Result<()> {
    let id = p["toolCallId"]
        .as_str()
        .map(str::to_owned)
        .unwrap_or_else(|| {
            asr_core::identity::derive_id(&[&c.session, &c.pos.to_string(), &c.slot.to_string()])
        });
    let mut r = json!({"type":"tool_call","callId":id,"requestedBy":if parent.is_some(){"code"}else{"model"}});
    if let Some(name) = p["toolName"].as_str() {
        r["name"] = json!(name);
    }
    if let Some(input) = p.get("input") {
        r["input"] = input.clone();
    }
    if let Some(parent) = parent {
        r["parentCallId"] = json!(parent);
    }
    c.emit(s, r, None, Some(&format!("mux-call:{id}")))?;
    if matches!(
        p["state"].as_str(),
        Some("output-available" | "output-redacted" | "output-error")
    ) {
        let mut r = json!({"type":"tool_result","callId":id,"status":if p["failed"] == true || p["state"] == "output-error" {"failed"}else{"unknown"},"_meta":{c.agent.domain():{"native":p}}});
        if p["state"] == "output-redacted" {
            r["truncated"] = json!(true);
            c.loss("tool_output");
        }
        // Native output can differ from the model-facing result.
        c.loss("tool_output");
        c.result(s, r)?;
    }
    Ok(())
}
