//! Continue saved sessions. Model titles remain configuration evidence.
use crate::{common::Context, documents as d, spool::Spool, Agent, Result, Summary};
use serde_json::{json, Value};
use std::path::Path;
pub fn stage(s: &mut Spool, _: &Path, v: &Value, summary: &mut Summary) -> Result<()> {
    let Some(id) = d::string(v, &["sessionId"]) else {
        summary.diagnostic("unidentified_source");
        return Ok(());
    };
    d::header(s, Agent::Continue, &id, v, summary)?;
    d::metadata(s, &id, v, &["history"])?;
    if let Some(history) = v["history"].as_array() {
        for item in history {
            d::store(s, &id, "history", item)?;
        }
    } else {
        summary.diagnostic("missing_source_history");
        d::store(s, &id, "gap", &Value::Null)?;
    }
    if let Some(mode) = v["mode"].as_str() {
        d::record(
            s,
            &id,
            json!({"type":"session_info","agentSettings":{"mode":mode}}),
            &Value::Null,
        )?;
    }
    let mut usage = json!({});
    for (from, to) in [
        ("promptTokens", "inputTokens"),
        ("completionTokens", "outputTokens"),
    ] {
        if let Some(n) = v["usage"][from]
            .as_u64()
            .filter(|n| *n <= 9_007_199_254_740_991)
        {
            usage[to] = json!(n);
        }
    }
    if usage.as_object().is_some_and(|o| !o.is_empty()) {
        d::record(
            s,
            &id,
            json!({"type":"session_info","usage":usage}),
            &Value::Null,
        )?;
    }
    Ok(())
}
pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if v["kind"] != "history" {
        return d::project(s, c, v);
    }
    let item = &v["value"];
    if let Some(message) = item.get("message") {
        let mut message = message.clone();
        if message.get("timestamp").is_none() {
            if let Some(ts) = d::time(item) {
                message["timestamp"] = json!(ts);
            }
        }
        if message.get("id").is_none() {
            if let Some(id) = item.get("id") {
                message["id"] = id.clone();
            }
        }
        d::chat(s, c, &message)?;
    }
    for state in item["toolCallStates"].as_array().into_iter().flatten() {
        c.source = json!({});
        if let Some(ts) = d::time(item) {
            c.source["ts"] = json!(ts);
        }
        let call = state.get("toolCall");
        if let Some(call) = call {
            d::call(s, c, call, false)?;
        }
        // The saved state is a snapshot. It supplies no separate approval history.
        if let Some(content) = d::alias(state, &["output", "result", "content"]) {
            let mut state = state.clone();
            if let Some(id) = d::string(&state, &["toolCallId"])
                .or_else(|| call.and_then(|v| d::string(v, &["id"])))
            {
                state["tool_call_id"] = json!(id);
                state.as_object_mut().unwrap().remove("toolCallId");
            }
            d::result(s, c, &state, content)?;
        }
    }
    if let Some(summary) = item["conversationSummary"].as_str() {
        c.source = json!({});
        c.emit(s,json!({"type":"message","role":"user","author":"harness","origin":"compaction","content":[{"type":"text","text":summary}]}),None,None)?;
        c.loss("native_history");
        c.emit(s, json!({"type":"gap","reason":"not_retained"}), None, None)?;
    }
    c.vendor(s, item)
}
