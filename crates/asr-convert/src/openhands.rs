//! OpenHands event files use their native conversation directory identity.
use crate::{common::Context, documents as d, spool::Spool, Agent, Result, Summary};
use serde_json::{json, Value};
use std::path::Path;
pub fn stage(s: &mut Spool, path: &Path, v: &Value, summary: &mut Summary) -> Result<()> {
    let legacy_id = path
        .parent()
        .filter(|p| p.file_name().is_some_and(|n| n == "events"))
        .and_then(Path::parent)
        .and_then(Path::file_name)
        .and_then(|v| v.to_str())
        .map(str::to_owned);
    let storage_id = legacy_id.or_else(|| {
        let directory = path.parent()?;
        (directory.parent()?.file_name()? == "v1_conversations").then_some(())?;
        directory.file_name()?.to_str().map(str::to_owned)
    });
    let Some(id) = d::string(v, &["session_id", "sessionId", "conversation_id"]).or(storage_id)
    else {
        summary.diagnostic("unidentified_source");
        return Ok(());
    };
    d::header(s, Agent::OpenHands, &id, &Value::Null, summary)?;
    d::store(s, &id, "event", v)
}
pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if v["kind"] != "event" {
        return d::project(s, c, v);
    }
    let e = &v["value"];
    c.source = json!({});
    if let Some(ts) = d::time(e) {
        c.source["ts"] = json!(ts);
    }
    if e.get("observation").is_some() {
        let observation = e.get("observation").filter(|v| v.is_object()).unwrap_or(e);
        let mut result = observation.clone();
        if let Some(id) = e.get("id") {
            result["id"] = id.clone();
        }
        if let Some(id) = d::string(e, &["tool_call_id", "toolCallId", "tool_use_id"]) {
            result["tool_call_id"] = json!(id);
        }
        let content =
            d::alias(observation, &["content", "output", "result"]).unwrap_or(&Value::Null);
        d::result(s, c, &result, content)?;
    } else if e.get("action").is_some() {
        let action = e
            .get("action")
            .filter(|v| v.is_object())
            .unwrap_or(&e["args"]);
        let kind = d::string(action, &["kind", "name", "tool", "tool_name"])
            .or_else(|| e["action"].as_str().map(str::to_owned));
        if matches!(kind.as_deref(), Some("message" | "MessageAction")) {
            let role = if e["source"] == "user" {
                "user"
            } else {
                "assistant"
            };
            let mut m = json!({"role":role,"content":action.get("message").or_else(||action.get("content")).unwrap_or(&Value::Null)});
            if e["source"] == "user" {
                m["author"] = json!("human");
                m["origin"] = json!("prompt");
            }
            if let Some(ts) = d::time(e) {
                m["timestamp"] = json!(ts);
            }
            d::chat(s, c, &m)?;
        } else {
            let mut call = json!({});
            if let Some(id) = e.get("id") {
                call["id"] = id.clone();
            }
            if let Some(name) = kind {
                call["name"] = json!(name);
            }
            if let Some(id) = d::string(e, &["tool_call_id", "toolCallId", "tool_use_id"]) {
                call["call_id"] = json!(id);
            }
            if let Some(input) = d::alias(action, &["arguments", "args", "input", "parameters"]) {
                call["input"] = input.clone();
            } else if let Some(args) = e.get("args") {
                call["input"] = args.clone();
            } else if action.is_object() {
                let mut input = action.clone();
                for key in ["kind", "name", "tool", "tool_name"] {
                    input.as_object_mut().unwrap().remove(key);
                }
                call["input"] = input;
            }
            d::call(s, c, &call, e["source"] == "agent")?;
        }
    } else if let Some(message) = e.get("llm_message") {
        let mut m = message.clone();
        if let Some(ts) = d::time(e) {
            m["timestamp"] = json!(ts);
        }
        if let Some(id) = e.get("id") {
            m["id"] = id.clone();
        }
        d::chat(s, c, &m)?;
    }
    c.vendor(s, e)
}
