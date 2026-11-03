use super::helpers::*;
use crate::{common::Context, spool::Spool, Result};
use serde_json::{json, Value};
pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if v.get("sessionId").is_some() {
        return Ok(());
    }
    let role = match v["type"].as_str() {
        Some("user") => "user",
        Some("tabnine" | "gemini") => "assistant",
        _ => return Ok(()),
    };
    let mut content = parts(&v["content"], c);
    for t in v["thoughts"].as_array().into_iter().flatten() {
        if let Some(t) = t["description"].as_str() {
            content.push(crate::common::reasoning(Some(t), Some("summary")));
        }
    }
    let mut m = json!({"type":"message","role":role,"content":content});
    if role == "assistant" {
        m["author"] = json!("model");
    }
    c.emit(s, m, native_id(v), None)?;
    // Per-message counters lack a model-call boundary and are retained in vendor evidence.
    if v["tokens"].is_object() {
        c.loss("usage_scope");
    }
    for t in v["toolCalls"].as_array().into_iter().flatten() {
        call(
            s,
            c,
            string(&t["id"]),
            t["name"].as_str(),
            t.get("args"),
            true,
            None,
            None,
            None,
        )?;
        if let Some(raw) = t.get("result") {
            let mut r = json!({"type":"tool_result","status":match t["status"].as_str(){Some("success"|"completed")=>"completed",Some("error")=>"failed",Some("cancelled")=>"cancelled",_=>"unknown"}});
            if let Some(id) = string(&t["id"]) {
                r["callId"] = json!(id);
            }
            meta(c, &mut r, "nativeResult", raw);
            c.result(s, r)?;
        }
    }
    Ok(())
}
