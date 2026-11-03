//! Legacy JSONL archive mapping. Current SQLite storage is a separate adapter.
use super::{helpers::*, pi};
use crate::{common::Context, spool::Spool, Result};
use serde_json::{json, Value};
pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    match v["type"].as_str() {
        Some("message") => pi::message_entry(s, c, v)?,
        Some("thinking_level_change") => {
            if let Some(e) = v
                .get("thinkingLevel")
                .filter(|e| e.is_string() || e.is_null())
            {
                c.settings(s, json!({"modelSettings":{"reasoningEffort":e}}))?;
            }
        }
        Some("session_info") => {
            if let Some(t) = v["name"].as_str() {
                c.info(s, json!({"type":"session_info","title":t}))?;
            }
        }
        Some("compaction" | "branch_summary" | "reset") => compaction(
            s,
            c,
            v.get("summary"),
            v["historyRetained"] == false || v["type"] == "reset",
        )?,
        Some("custom") if v["customType"] == "openclaw.system-prompt" => {
            if let Some(t) = v["data"]["renderedPrefix"].as_str() {
                c.emit(s,json!({"type":"message","role":"system","author":"harness","origin":"instructions","content":[{"type":"text","text":t}]}),None,None)?;
            }
            tools(s, c, &v["data"]["tools"])?;
        }
        _ => {}
    }
    Ok(())
}
