//! Cursor's documented agent-transcripts layout supplies the native session ID.
use crate::{
    batch_a as b,
    common::{self, Context},
    spool::Spool,
    Agent, Result, Summary,
};
use serde_json::{json, Value};
use std::path::Path;

pub fn stage(s: &mut Spool, p: &Path, n: &mut Summary) -> Result<()> {
    let id = p
        .parent()
        .and_then(Path::file_name)
        .and_then(|v| v.to_str());
    let valid = id.is_some_and(|id| {
        let name = p.file_name().unwrap().to_string_lossy();
        (name == format!("{id}.jsonl")
            || name == format!("{id}.jsonl.zst")
            || name == format!("{id}.jsonl.zstd"))
            && p.parent()
                .and_then(Path::parent)
                .is_some_and(|p| p.ends_with("agent-transcripts"))
            && p.ancestors()
                .nth(4)
                .is_some_and(|p| p.ends_with("projects"))
    });
    if !valid {
        n.files += 1;
        n.diagnostic("unidentified_source");
        return Ok(());
    }
    let id = id.unwrap();
    let mut h = b::header(Agent::Cursor, id);
    h["missing"].as_array_mut().unwrap().extend([
        json!("reasoning"),
        json!("call_ids"),
        json!("ide_and_blob_stores"),
        json!("external_tool_files"),
    ]);
    s.session(id, &h)?;
    b::lines(s, p, id, n)
}
pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if b::gap(s, c, v)? {
        return Ok(());
    }
    b::time(c, &v["timestamp"]);
    let role = v["role"].as_str().or(v["message"]["role"].as_str());
    let normal = matches!(role, Some("user" | "assistant"))
        && v.get("event").is_none()
        && v.get("status").is_none()
        && v.get("type").is_none_or(|v| v == "message")
        && (v["message"]["role"].is_null() || v["message"]["role"].as_str() == role);
    let summary = role.is_none()
        && (matches!(v["event"].as_str(), Some("summary" | "turn_ended"))
            || matches!(v["type"].as_str(), Some("summary" | "turn_ended")))
        && v.get("status").is_none_or(|v| v == "completed");
    if !normal && !summary {
        return c.vendor(s, v);
    }
    let content = &v["message"]["content"];
    if !content.is_array() {
        return c.vendor(s, v);
    }
    let text: Vec<_> = content
        .as_array()
        .unwrap()
        .iter()
        .filter(|p| p["type"] == "text")
        .filter_map(|p| p["text"].as_str())
        .map(common::text)
        .collect();
    if !text.is_empty() {
        let mut r = json!({"type":"message","role":role.unwrap_or("user"),"content":text});
        if role == Some("assistant") {
            r["author"] = json!("model");
        }
        if summary {
            r["author"] = json!("harness");
            r["origin"] = json!("notice");
        }
        c.emit(s, r, v["id"].as_str(), None)?;
    }
    for p in content.as_array().unwrap() {
        if normal && role == Some("assistant") && p["type"] == "tool_use" {
            b::call(
                s,
                c,
                p,
                p["id"].as_str(),
                p["name"].as_str(),
                p.get("input"),
                None,
            )?;
        } else if normal && p["type"] == "tool_result" {
            let mut r = json!({"type":"tool_result","status":match p["is_error"].as_bool(){Some(true)=>"failed",Some(false)=>"completed",None=>"unknown"}});
            if let Some(id) = p["tool_use_id"].as_str() {
                r["callId"] = json!(id);
            }
            if let Some(content) = p.get("content") {
                r["content"] = json!(common::parts(content, c.agent));
            }
            c.result(s, r)?;
        }
    }
    c.vendor(s, v)
}
