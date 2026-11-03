use super::helpers::*;
use crate::{common::Context, spool::Spool, Result};
use serde_json::{json, Value};
pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    let body = &v["message"]["content"];
    let has_results = body
        .as_array()
        .is_some_and(|a| a.iter().any(|p| p["type"] == "tool_result"));
    if let Some(role) = v["type"]
        .as_str()
        .filter(|r| matches!(*r, "user" | "assistant"))
    {
        if !body.is_null() && (has_results || v.get("toolUseResult").is_none()) {
            blocks(s, c, v, role, body)?;
        }
    }
    if !has_results {
        if let Some(raw) = v.get("toolUseResult").or_else(|| {
            matches!(
                v["type"].as_str(),
                Some("tool_result" | "tool_output" | "function_call_output")
            )
            .then_some(v)
        }) {
            let id = [
                "callId",
                "toolCallId",
                "call_id",
                "tool_call_id",
                "tool_use_id",
                "toolUseId",
            ]
            .into_iter()
            .find_map(|k| raw[k].as_str().or_else(|| v[k].as_str()));
            let mut r = json!({"type":"tool_result","status":status(&raw["is_error"])});
            if let Some(id) = id {
                r["callId"] = json!(id);
            }
            meta(c, &mut r, "displayResult", raw);
            c.result(s, r)?;
        }
    }
    Ok(())
}
