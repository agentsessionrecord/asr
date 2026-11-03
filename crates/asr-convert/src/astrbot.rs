//! AstrBot public conversation UUIDs and retained context snapshots.
use crate::{common::Context, spool::Spool, sqlite as q, Result};
use rusqlite::Connection;
use serde_json::Value;
pub(crate) fn stage(db: &Connection, s: &Spool, id: &str, row: &Value) -> Result<()> {
    if row.get("_gap").is_some() {
        return q::push(s, id, "state", row.clone());
    }
    match q::parse(&row["content"]) {
        Some(Value::Array(messages)) => {
            for message in messages {
                q::push(s, id, "message", message)?;
            }
        }
        _ => q::gap(s, id, "unparseable")?,
    }
    q::push(s, id, "state", q::without(row, &["content"]))?;
    if q::columns(db, "provider_stats")?
        .iter()
        .any(|c| c == "conversation_id")
    {
        q::rows(
            db,
            "provider_stats",
            Some(("conversation_id", id)),
            &["id"],
            s.limit,
            |v| q::push(s, id, "provider_stats", v),
        )?;
    }
    Ok(())
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
