//! NanoClaw central session inventory and per-session mailbox databases.
use crate::{common::Context, documents as d, spool::Spool, Agent, Result, Summary};
use serde_json::{json, Value};
use std::path::Path;
pub fn stage(s: &mut Spool, path: &Path, summary: &mut Summary) -> Result<()> {
    let db = d::sqlite(path)?;
    let data = path.parent().unwrap_or(Path::new("."));
    d::rows(&db, "sessions", s, summary, |s, session, summary| {
        let Some(id) = d::scalar(&session["id"]) else {
            summary.diagnostic("unidentified_source_row");
            return Ok(());
        };
        d::header(s, Agent::NanoClaw, &id, &session, summary)?;
        d::store(s, &id, "metadata", &session)?;
        let Some(group) = d::scalar(&session["agent_group_id"]) else {
            summary.diagnostic("missing_agent_group");
            return Ok(());
        };
        if [&group, &id]
            .iter()
            .any(|v| v.contains(['/', '\\']) || matches!(v.as_str(), "." | ".."))
        {
            summary.diagnostic("invalid_session_reference");
            return Ok(());
        }
        let directory = data.join("v2-sessions").join(group).join(&id);
        if directory.exists()
            && std::fs::canonicalize(&directory)?
                .strip_prefix(std::fs::canonicalize(data)?)
                .is_err()
        {
            return Err(crate::Error::Invalid(
                "native session directory crosses its data root".into(),
            ));
        }
        let mut found = false;
        for (file, table, role) in [
            ("inbound.db", "messages_in", "user"),
            ("outbound.db", "messages_out", "assistant"),
        ] {
            let component = directory.join(file);
            if !component.is_file() {
                continue;
            }
            if std::fs::symlink_metadata(&component)?
                .file_type()
                .is_symlink()
            {
                summary.diagnostic("unavailable_source_component");
                continue;
            }
            found = true;
            let messages = d::sqlite(&component)?;
            if !d::table(&messages, table)? {
                summary.diagnostic("missing_source_table");
                d::store(s, &id, "gap", &Value::Null)?;
                continue;
            }
            d::rows(&messages, table, s, summary, |s, row, _| {
                if row["_gap"] == true {
                    return d::store(s, &id, "gap", &Value::Null);
                }
                let mut m = row.clone();
                m["role"] = json!(role);
                // Inbound includes schedules, wakeups and external messages.
                // None of these labels alone identifies a human author.
                if role == "user" {
                    m["origin"] = json!(if row["trigger"] == "schedule" {
                        "scheduled"
                    } else {
                        "external"
                    });
                }
                d::store(s, &id, "message", &m)
            })?;
        }
        if !found {
            summary.diagnostic("missing_source_mailbox");
            d::store(s, &id, "gap", &Value::Null)?;
        }
        Ok(())
    })?;
    db.execute_batch("ROLLBACK")?;
    Ok(())
}
pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    // Independent inbox and outbox logs have no shared source sequence.
    c.loss("cross_mailbox_order");
    d::project(s, c, v)
}
