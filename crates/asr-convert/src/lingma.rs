//! Lingma request prompts and retained answer summaries.
use crate::{
    common::{self, Context},
    spool::Spool,
    sqlite as q, Result,
};
use rusqlite::Connection;
use serde_json::{json, Value};
pub(crate) fn stage(db: &Connection, s: &Spool, id: &str) -> Result<()> {
    q::rows(
        db,
        "chat_record",
        Some(("session_id", id)),
        &[],
        s.limit,
        |v| q::push(s, id, "chat_record", v),
    )
}
pub(crate) fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if q::common(s, c, v)? {
        return Ok(());
    }
    let d = &v["data"];
    if let Some(prompt) = d["chat_prompt"].as_str() {
        let mut r = json!({"type":"message","role":"user","content":[common::text(prompt)]});
        q::stamp(
            &mut r,
            &d["gmt_create"],
            d["gmt_create"]
                .as_i64()
                .is_some_and(|n| n.unsigned_abs() > 1_000_000_000_000),
        );
        c.emit(s, r, None, None)?;
    }
    if let Some(summary) = d["summary"].as_str().filter(|s| !s.is_empty()) {
        c.loss("message_summaries");
        c.emit(s,json!({"type":"message","role":"assistant","content":[common::text(summary)],"truncated":true}),None,None)?;
    }
    q::vendor(s, c, v)
}
