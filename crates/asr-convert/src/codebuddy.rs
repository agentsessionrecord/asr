//! CodeBuddy CLI JSONL and extension session indexes.
use crate::{common::Context, documents as d, spool::Spool, Agent, Result, Summary};
use serde_json::{json, Value};
use std::path::Path;
pub fn stage(s: &mut Spool, path: &Path, summary: &mut Summary) -> Result<()> {
    if path.extension().is_some_and(|e| e == "jsonl") {
        let mut session = None;
        // Identity must be recorded. An arbitrary JSONL basename supplies none.
        d::jsonl(s, path, summary, |s, v, summary| {
            if let Some(id) = d::string(&v, &["sessionId", "session_id"]) {
                d::header(s, Agent::CodeBuddy, &id, &v, summary)?;
                session = Some(id);
            }
            if let Some(id) = &session {
                d::store(s, id, if v["_gap"] == true { "gap" } else { "buddy" }, &v)?;
            } else {
                summary.diagnostic("unidentified_source_line");
            }
            Ok(())
        })?;
    } else {
        let Some(index) = d::read(s, path, summary)? else {
            return Ok(());
        };
        let Some(id) = d::string(&index, &["sessionId", "session_id", "id"]).or_else(|| {
            let directory = path.parent()?;
            directory.join("messages").is_dir().then_some(())?;
            directory.file_name()?.to_str().map(str::to_owned)
        }) else {
            summary.diagnostic("unidentified_source");
            return Ok(());
        };
        d::header(s, Agent::CodeBuddy, &id, &index, summary)?;
        d::metadata(s, &id, &index, &["messages"])?;
        for item in index["messages"].as_array().into_iter().flatten() {
            if item.get("content").is_some() || item.get("message").is_some() {
                d::store(s, &id, "buddy", item)?;
                continue;
            }
            let Some(message_id) = d::string(item, &["id"])
                .filter(|id| !id.contains(['/', '\\']) && id != "." && id != "..")
            else {
                summary.diagnostic("invalid_message_reference");
                continue;
            };
            let directory = path.parent().unwrap();
            let candidate = directory
                .join("messages")
                .join(format!("{message_id}.json"));
            if candidate.exists()
                && std::fs::canonicalize(&candidate)?
                    .strip_prefix(std::fs::canonicalize(directory)?)
                    .is_err()
            {
                summary.diagnostic("invalid_message_reference");
                d::store(s, &id, "gap", &Value::Null)?;
                continue;
            }
            if !candidate.is_file()
                || std::fs::symlink_metadata(&candidate)?
                    .file_type()
                    .is_symlink()
            {
                summary.diagnostic("unavailable_source_message");
                d::store(s, &id, "gap", &Value::Null)?;
                continue;
            }
            if let Some(mut message) = d::read(s, &candidate, summary)? {
                for field in ["id", "role", "type"] {
                    if message.get(field).is_none() {
                        if let Some(v) = item.get(field) {
                            message[field] = v.clone();
                        }
                    }
                }
                d::store(s, &id, "buddy", &message)?;
            } else {
                d::store(s, &id, "gap", &Value::Null)?;
            }
        }
    }
    Ok(())
}
pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if v["kind"] != "buddy" {
        return d::project(s, c, v);
    }
    let raw = &v["value"];
    let mut message = match raw.get("message") {
        Some(Value::String(text)) => {
            asr_core::jsonl::decode(text).unwrap_or_else(|_| json!({"content":text}))
        }
        Some(value) if value.is_object() => value.clone(),
        _ => raw.clone(),
    };
    for field in ["role", "type", "id", "timestamp"] {
        if message.get(field).is_none() {
            if let Some(value) = raw.get(field) {
                message[field] = value.clone();
            }
        }
    }
    d::chat(s, c, &message)
}
