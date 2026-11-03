use super::helpers::*;
use crate::{common::Context, spool::Spool, Result};
use serde_json::{json, Value};
pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    // Rendered trajectory steps do not establish model request content or user authorship.
    if v["type"] == "PLANNER_RESPONSE" {
        let mut r = json!({"type":"message","role":"assistant","author":"model","content":[]});
        meta(c, &mut r, "displayContent", &v["content"]);
        if let Some(t) = v["thinking"].as_str() {
            r["content"] = json!([crate::common::reasoning(Some(t), None)]);
        }
        c.emit(s, r, None, None)?;
        c.loss("message_content");
    }
    for t in v["tool_calls"].as_array().into_iter().flatten() {
        call(
            s,
            c,
            string(&t["id"]),
            t["name"].as_str(),
            t.get("args").or_else(|| t.get("arguments")),
            matches!(v["source"].as_str(), Some("planner" | "assistant")),
            None,
            None,
            None,
        )?;
    }
    Ok(())
}
