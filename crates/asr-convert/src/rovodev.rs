//! Rovo Dev saved context and Pydantic message parts.
use crate::{common::Context, documents as d, spool::Spool, Agent, Result, Summary};
use serde_json::{json, Value};
use std::path::Path;
pub fn stage(s: &mut Spool, path: &Path, v: &Value, summary: &mut Summary) -> Result<()> {
    let metadata_path = path
        .parent()
        .unwrap_or(Path::new("."))
        .join("metadata.json");
    let metadata = if metadata_path.is_file() {
        d::read(s, &metadata_path, summary)?.unwrap_or(Value::Null)
    } else {
        Value::Null
    };
    let id = d::string(v, &["session_id", "sessionId"])
        .or_else(|| d::string(&metadata, &["session_id", "sessionId"]));
    let Some(id) = id else {
        summary.diagnostic("unidentified_source");
        return Ok(());
    };
    d::header(s, Agent::RovoDev, &id, &metadata, summary)?;
    if let Some(parent) = d::string(
        &metadata,
        &[
            "parent_session_id",
            "parentSessionId",
            "forked_from_session_id",
        ],
    ) {
        d::parent(s, &id, Agent::RovoDev, &parent, "fork")?;
    }
    d::metadata(s, &id, v, &["message_history", "messages"])?;
    if let Some(messages) = d::alias(v, &["message_history", "messages"]).and_then(Value::as_array)
    {
        for message in messages {
            d::store(s, &id, "rovo", message)?;
        }
    } else {
        summary.diagnostic("missing_source_history");
        d::store(s, &id, "gap", &Value::Null)?;
    }
    Ok(())
}
pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if v["kind"] != "rovo" {
        return d::project(s, c, v);
    }
    let m = &v["value"];
    if let Some(parts) = m["parts"].as_array() {
        for part in parts {
            let kind = d::string(part, &["part_kind", "kind", "type"]);
            let mut p = part.clone();
            if p.get("timestamp").is_none() {
                if let Some(ts) = d::time(m) {
                    p["timestamp"] = json!(ts);
                }
            }
            let role = match kind.as_deref() {
                Some("user-prompt") => Some("user"),
                Some("system-prompt") => Some("system"),
                Some("text") => Some("assistant"),
                _ => None,
            };
            if let Some(role) = role {
                p["role"] = json!(role);
                d::chat(s, c, &p)?;
            } else if kind.as_deref() == Some("tool-call") {
                if let Some(id) = p.get("tool_call_id").cloned() {
                    p["id"] = id;
                    p.as_object_mut().unwrap().remove("tool_call_id");
                }
                if let Some(name) = p.get("tool_name").cloned() {
                    p["name"] = name;
                    p.as_object_mut().unwrap().remove("tool_name");
                }
                c.source = json!({});
                if let Some(ts) = d::time(&p) {
                    c.source["ts"] = json!(ts);
                }
                d::call(s, c, &p, true)?;
            } else if kind.as_deref() == Some("tool-return") {
                c.source = json!({});
                if let Some(ts) = d::time(&p) {
                    c.source["ts"] = json!(ts);
                }
                d::result(s, c, &p, &p["content"])?;
            } else {
                c.vendor(s, part)?;
            }
        }
    } else {
        d::chat(s, c, m)?;
    }
    Ok(())
}
