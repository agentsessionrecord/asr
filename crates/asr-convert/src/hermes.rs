//! Hermes sessions and messages from a read-only SQLite transaction.
use crate::{common::Context, documents as d, spool::Spool, Agent, Result, Summary};
use serde_json::{json, Value};
use std::path::Path;
pub fn stage(s: &mut Spool, path: &Path, summary: &mut Summary) -> Result<()> {
    let db = d::sqlite(path)?;
    d::rows(&db, "sessions", s, summary, |s, v, summary| {
        let Some(id) = d::scalar(&v["id"]) else {
            summary.diagnostic("unidentified_source_row");
            return Ok(());
        };
        d::header(s, Agent::Hermes, &id, &v, summary)?;
        if let Some(parent) = d::string(&v, &["parent_session_id"]) {
            d::parent(s, &id, Agent::Hermes, &parent, "subagent")?;
        }
        d::store(
            s,
            &id,
            if v["_gap"] == true { "gap" } else { "metadata" },
            &v,
        )
    })?;
    d::rows(&db, "messages", s, summary, |s, v, summary| {
        let Some(id) = d::string(&v, &["session_id"]) else {
            summary.diagnostic("unidentified_source_row");
            return Ok(());
        };
        let exists: bool = s.db.query_row(
            "SELECT EXISTS(SELECT 1 FROM sessions WHERE id=?1)",
            [&id],
            |r| r.get(0),
        )?;
        if !exists {
            summary.diagnostic("orphan_source_message");
            return Ok(());
        }
        d::store(
            s,
            &id,
            if v["_gap"] == true {
                "gap"
            } else {
                "hermes_message"
            },
            &v,
        )
    })?;
    d::rows(&db, "sessions", s, summary, |s, v, _| {
        if let Some(id) = d::scalar(&v["id"]) {
            if v["_gap"] != true {
                d::store(s, &id, "session", &v)?;
            }
        }
        Ok(())
    })?;
    db.execute_batch("ROLLBACK")?;
    Ok(())
}
pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    let native = &v["value"];
    match v["kind"].as_str() {
        Some("session") => {
            c.source = json!({});
            let mut info = json!({"type":"session_info"});
            if let Some(end) = native.get("ended_at").and_then(d::timestamp) {
                info["endedAt"] = json!(end);
            }
            let mut usage = json!({});
            // Hermes stores uncached input separately from cache reads and writes.
            let input = ["cache_read_tokens", "cache_write_tokens"].iter().fold(
                native["input_tokens"].as_u64(),
                |total, key| match native.get(*key) {
                    Some(component) => total?.checked_add(component.as_u64()?),
                    None => total,
                },
            );
            if let Some(n) = input.filter(|n| *n <= 9_007_199_254_740_991) {
                usage["inputTokens"] = json!(n);
            }
            for (from, to) in [
                ("output_tokens", "outputTokens"),
                ("cache_read_tokens", "cacheReadTokens"),
                ("cache_write_tokens", "cacheWriteTokens"),
                ("reasoning_tokens", "reasoningTokens"),
            ] {
                if let Some(n) = native[from]
                    .as_u64()
                    .filter(|n| *n <= 9_007_199_254_740_991)
                {
                    usage[to] = json!(n);
                }
            }
            if usage.as_object().is_some_and(|o| !o.is_empty()) {
                info["usage"] = usage;
            }
            for (field, source) in [
                ("actual_cost_usd", "provider_reported"),
                ("estimated_cost_usd", "harness_estimated"),
            ] {
                if let Some(amount) = native[field]
                    .as_number()
                    .filter(|n| n.as_f64().is_some_and(|n| n >= 0.0))
                {
                    info["cost"] = json!({"amount":amount,"currency":"USD","source":source});
                    break;
                }
            }
            if info.as_object().unwrap().len() > 1 {
                c.info(s, info)?;
            }
            c.vendor(s, native)
        }
        Some("hermes_message") => {
            let mut m = native.clone();
            if let Some(encoded) = native["content"]
                .as_str()
                .and_then(|s| s.strip_prefix("\0json:"))
            {
                if let Ok(content) = asr_core::jsonl::decode(encoded) {
                    m["content"] = content;
                }
            }
            if let Some(encoded) = native["tool_calls"].as_str() {
                if let Ok(calls) = asr_core::jsonl::decode(encoded) {
                    m["tool_calls"] = calls;
                }
            }
            let mut parts = Vec::new();
            for field in ["reasoning", "reasoning_content"] {
                if let Some(text) = native[field].as_str() {
                    if !parts.iter().any(|v: &Value| v["text"] == text) {
                        parts.push(crate::common::reasoning(Some(text), None));
                    }
                }
            }
            if !parts.is_empty() {
                if let Some(text) = m["content"].as_str() {
                    parts.push(crate::common::text(text));
                } else if let Some(content) = m["content"].as_array() {
                    parts.extend(content.clone());
                }
                m["content"] = json!(parts);
            }
            // A SQL NULL means the optional field was absent, not an empty message.
            if m["content"].is_null() {
                m.as_object_mut().unwrap().remove("content");
            }
            if m["tool_calls"].is_null() {
                m.as_object_mut().unwrap().remove("tool_calls");
            }
            d::chat(s, c, &m)
        }
        _ => d::project(s, c, v),
    }
}
