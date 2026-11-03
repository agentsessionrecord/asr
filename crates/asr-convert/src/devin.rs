//! Devin message-node forest, retained branches and terminal tool snapshots.
use crate::{
    common::{self, Context},
    spool::Spool,
    sqlite as q, Result,
};
use rusqlite::Connection;
use serde_json::{json, Value};
pub(crate) fn stage(db: &Connection, s: &Spool, id: &str, row: &Value) -> Result<()> {
    q::rows(
        db,
        "message_nodes",
        Some(("session_id", id)),
        &["node_id"],
        s.limit,
        |mut row| {
            if row.get("_gap").is_some() {
                return q::push(s, id, "node", row);
            }
            for field in ["chat_message", "metadata"] {
                if !row[field].is_null() {
                    match q::parse(&row[field]) {
                        Some(value) => row[field] = value,
                        _ => return q::gap(s, id, "unparseable"),
                    }
                }
            }
            q::push(s, id, "node", row)
        },
    )?;
    q::rows(
        db,
        "tool_call_state",
        Some(("session_id", id)),
        &["tool_call_id"],
        s.limit,
        |mut row| {
            for field in ["tool_call_json", "tool_call_update_json"] {
                if let Some(value) = q::parse(&row[field]) {
                    row[field] = value;
                }
            }
            q::push(s, id, "tool_state", row)
        },
    )?;
    for table in ["prompt_history", "rendered_commits", "subagent_heads"] {
        q::rows(
            db,
            table,
            Some(("session_id", id)),
            &["id", "agent_id"],
            s.limit,
            |v| q::push(s, id, table, v),
        )?;
    }
    q::push(s, id, "state", row.clone())
}
pub(crate) fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if q::common(s, c, v)? {
        return Ok(());
    }
    let row = &v["data"];
    if v["table"] == "state" {
        q::state(s, c, row)?;
        if let Some(mode) = row["agent_mode"].as_str() {
            c.settings(s, json!({"mode":mode}))?;
        }
    } else if v["table"] == "node" {
        let d = &row["chat_message"];
        let role = d["role"].as_str().unwrap_or("");
        let inf = if role == "assistant" {
            d["metadata"]["request_id"].as_str()
        } else {
            None
        };
        if role == "tool" {
            let mut r = json!({"type":"tool_result","status":"unknown","content":common::parts(&d["content"],c.agent)});
            if let Some(id) = d["tool_call_id"].as_str() {
                r["callId"] = json!(id);
            }
            let timing = &d["metadata"]["extensions"]["chisel/tool_call_timing"];
            if let Some(n) = q::count(&timing["duration_ms"]) {
                r["durationMs"] = json!(n);
            }
            q::stamp(&mut r, &timing["finished_at"], false);
            q::receipt(s, c, r, None, None)?;
        } else if matches!(role, "user" | "assistant" | "system" | "developer") {
            let mut r = json!({"type":"message","role":role,"content":common::parts(&d["content"],c.agent)});
            if role == "assistant" {
                r["author"] = json!("model");
            }
            if role == "user" && d["metadata"]["is_user_input"] == true {
                r["author"] = json!("human");
                r["origin"] = json!("prompt");
            }
            if row["metadata"]["is_system_prefix"] == true {
                r["author"] = json!("harness");
                r["origin"] = json!("injected");
            }
            let summary = role == "system" && row["metadata"]["summarized_from"].is_number();
            if summary {
                r["author"] = json!("harness");
                r["origin"] = json!("compaction");
            }
            if let Some(inf) = inf {
                r["inferenceId"] = json!(inf);
            }
            q::stamp(&mut r, &row["created_at"], false);
            c.emit(s, r, d["message_id"].as_str(), None)?;
            if summary {
                c.emit(s,json!({"type":"gap","reason":"not_retained","detail":"The source records a summary without an exact replaced range."}),None,None)?;
            }
            for t in d["tool_calls"].as_array().into_iter().flatten() {
                let f = t.get("function").unwrap_or(t);
                q::call(
                    s,
                    c,
                    t["id"].as_str(),
                    f["name"].as_str(),
                    f.get("arguments"),
                    None,
                    inf,
                )?;
            }
        }
        if let Some(inf) = inf {
            let mut r = json!({"type":"inference"});
            if let Some(u) = d["metadata"].get("metrics") {
                let mut usage = q::usage(
                    u,
                    "",
                    "output_tokens",
                    "cache_read_tokens",
                    "cache_creation_tokens",
                    true,
                );
                usage.as_object_mut().unwrap().remove("inputTokens");
                r["usage"] = usage;
                q::metadata(&mut r, c.agent, "metrics", u);
            }
            common::copy(&mut r, "stopReason", &d["metadata"], "finish_reason");
            c.emit(s, r, Some(inf), Some(&format!("inference:{inf}")))?;
        }
    } else if v["table"] == "tool_state" {
        let update = &row["tool_call_update_json"];
        let call = row["tool_call_id"].as_str();
        if let (Some(call), Some(status @ ("completed" | "failed"))) =
            (call, update["status"].as_str())
        {
            let mut r = json!({"type":"tool_result","callId":call,"status":status});
            let exit = &update["_meta"]["terminal_exit"];
            if let Some(code) = exit["exit_code"].as_i64() {
                r["exec"]["exitCode"] = json!(code);
            }
            if let Some(signal) = exit["signal"].as_str() {
                r["exec"]["signal"] = json!(signal);
            }
            q::receipt(s, c, r, None, None)?;
            for diff in update["content"]
                .as_array()
                .into_iter()
                .flatten()
                .filter(|p| p["type"] == "diff")
            {
                if let (Some(path), Some(after)) = (diff["path"].as_str(), diff["newText"].as_str())
                {
                    let mut r = json!({"type":"file_change","path":common::path(path,c.cwd.as_deref()),"op":if diff["oldText"].is_null(){"add"}else{"modify"},"status":if status=="completed"{"applied"}else{"failed"},"callId":call,"after":{"text":after}});
                    if let Some(before) = diff["oldText"].as_str() {
                        r["before"] = json!({"text":before});
                    }
                    q::receipt(s, c, r, None, None)?;
                }
            }
        }
    }
    q::vendor(s, c, v)
}
