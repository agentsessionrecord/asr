//! Auggie session documents and ordered request/response exchanges.
use crate::{common::Context, documents as d, spool::Spool, Agent, Result, Summary};
use serde_json::{json, Value};
use std::path::Path;
pub fn stage(s: &mut Spool, _: &Path, v: &Value, summary: &mut Summary) -> Result<()> {
    let Some(id) = d::string(v, &["sessionId", "session_id"]) else {
        summary.diagnostic("unidentified_source");
        return Ok(());
    };
    d::header(s, Agent::Auggie, &id, v, summary)?;
    if let Some(parent) = d::string(
        v,
        &[
            "parentConversationId",
            "parentSessionId",
            "parent_session_id",
        ],
    ) {
        d::parent(s, &id, Agent::Auggie, &parent, "subagent")?;
    }
    d::metadata(s, &id, v, &["chatHistory", "chat_history"])?;
    if let Some(history) = d::alias(v, &["chatHistory", "chat_history"]).and_then(Value::as_array) {
        for entry in history {
            d::store(s, &id, "exchange", entry)?;
        }
    } else {
        summary.diagnostic("missing_source_history");
        d::store(s, &id, "gap", &Value::Null)?;
    }
    Ok(())
}
pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if v["kind"] != "exchange" {
        return d::project(s, c, v);
    }
    let entry = &v["value"];
    let exchange = entry.get("exchange").unwrap_or(entry);
    c.source = json!({});
    if let Some(ts) = d::time(entry).or_else(|| d::time(exchange)) {
        c.source["ts"] = json!(ts);
    }
    for (role, text_keys, node_keys) in [
        (
            "user",
            ["request_message", "requestMessage"],
            ["request_nodes", "requestNodes"],
        ),
        (
            "assistant",
            ["response_text", "responseText"],
            ["response_nodes", "responseNodes"],
        ),
    ] {
        let mut parts = Vec::new();
        if let Some(text) = d::alias(exchange, &text_keys).and_then(Value::as_str) {
            parts.push(crate::common::text(text));
        } else if let Some(nodes) = d::alias(exchange, &node_keys).and_then(Value::as_array) {
            for node in nodes {
                let Some(o) = node.as_object() else {
                    continue;
                };
                let shape = o.len() == 1 && !o.contains_key("type")
                    || o.len() == 2 && node["type"].as_u64() == Some(0);
                if shape {
                    if let Some(text_node) = d::alias(node, &["text_node", "textNode"])
                        .filter(|n| n.as_object().is_some_and(|o| o.len() == 1))
                    {
                        if let Some(text) = text_node["content"].as_str() {
                            parts.push(crate::common::text(text));
                        }
                    }
                }
            }
        }
        if !parts.is_empty() {
            let mut r = json!({"type":"message","role":role,"content":parts});
            if role == "assistant" {
                r["author"] = json!("model");
            }
            c.emit(s, r, None, None)?;
        }
    }
    c.vendor(s, entry)
}
