//! Firebender stored chat snapshots. Call-owned child conversations remain evidence.
use crate::{common::Context, spool::Spool, sqlite as q, Result};
use rusqlite::Connection;
use serde_json::Value;
pub(crate) fn stage(db: &Connection, s: &Spool, id: &str, row: &Value) -> Result<()> {
    if row.get("_gap").is_some() {
        return q::push(s, id, "state", row.clone());
    }
    match q::parse(&row["messages_json"]) {
        Some(Value::Array(messages)) => {
            for m in messages {
                q::push(s, id, "message", m)?;
            }
        }
        _ => q::gap(s, id, "unparseable")?,
    }
    q::push(s, id, "state", q::without(row, &["messages_json"]))?;
    q::rows(
        db,
        "subagent_conversations",
        Some(("session_id", id)),
        &["tool_call_id"],
        s.limit,
        |v| q::push(s, id, "subagent_conversations", v),
    )
}
pub(crate) fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if q::common(s, c, v)? {
        return Ok(());
    }
    if v["table"] == "message" {
        q::message(s, c, &v["data"])?;
    } else if v["table"] == "state" {
        q::state(s, c, &v["data"])?;
    }
    q::vendor(s, c, v)
}
