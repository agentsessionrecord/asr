//! Cline API task histories and version 1 SDK message artifacts.
use crate::{common::Context, documents as d, spool::Spool, Agent, Result, Summary};
use serde_json::{json, Value};
use std::path::Path;
pub fn stage(s: &mut Spool, path: &Path, v: &Value, summary: &mut Summary) -> Result<()> {
    stage_task(s, Agent::Cline, path, v, summary)
}
pub fn stage_task(
    s: &mut Spool,
    agent: Agent,
    path: &Path,
    v: &Value,
    summary: &mut Summary,
) -> Result<()> {
    let metadata_path = path
        .parent()
        .unwrap_or(Path::new("."))
        .join("task_metadata.json");
    let metadata = if metadata_path.is_file() {
        d::read(s, &metadata_path, summary)?.unwrap_or(Value::Null)
    } else {
        Value::Null
    };
    let id = d::string(v, &["sessionId", "session_id"])
        .or_else(|| d::string(&metadata, &["id", "taskId", "task_id"]))
        .or_else(|| {
            let task = path.parent()?;
            (task.parent()?.file_name()? == "tasks")
                .then(|| task.file_name()?.to_str().map(str::to_owned))
                .flatten()
        });
    let Some(id) = id else {
        summary.diagnostic("unidentified_source");
        return Ok(());
    };
    d::header(
        s,
        agent,
        &id,
        if metadata.is_object() { &metadata } else { v },
        summary,
    )?;
    let name = path.file_name().unwrap_or_default().to_string_lossy();
    let parent = path.parent().unwrap_or(Path::new("."));
    if name == "claude_messages.json" && parent.join("api_conversation_history.json").is_file() {
        return Ok(());
    }
    if name == "ui_messages.json" && parent.join("api_conversation_history.json").is_file() {
        // API and display stores do not expose a shared total order.
        // Preserve the display snapshot as vendor evidence rather than duplicate actions.
        d::store(s, &id, "metadata", v)?;
        return Ok(());
    }
    if let Some(parent) = d::string(v, &["parent_session_id"]).or_else(|| {
        v.pointer("/origin/parentThreadId")
            .and_then(Value::as_str)
            .map(str::to_owned)
    }) {
        d::parent(s, &id, agent, &parent, "subagent")?;
    }
    if let Some(system) = v.get("system_prompt") {
        d::store(
            s,
            &id,
            "message",
            &json!({"role":"system","content":system}),
        )?;
    }
    let items = v.as_array().or_else(|| v["messages"].as_array());
    if let Some(items) = items {
        for item in items {
            d::store(
                s,
                &id,
                if name == "ui_messages.json" {
                    "ui"
                } else {
                    "message"
                },
                item,
            )?;
        }
    } else {
        summary.diagnostic("missing_source_history");
        d::store(s, &id, "gap", &Value::Null)?;
    }
    if v.is_object() {
        d::metadata(s, &id, v, &["messages", "system_prompt"])?;
    }
    if metadata.is_object() {
        d::metadata(s, &id, &metadata, &[])?;
    }
    Ok(())
}
pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if v["kind"] == "ui" {
        let item = &v["value"];
        if item["type"] == "say" && item["say"] == "text" && item["text"].is_string() {
            let mut m = item.clone();
            m["role"] = json!("assistant");
            m["content"] = item["text"].clone();
            d::chat(s, c, &m)?;
        } else {
            c.vendor(s, item)?;
        }
        return Ok(());
    }
    d::project(s, c, v)
}
