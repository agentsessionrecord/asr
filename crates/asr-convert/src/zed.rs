//! Zed thread 0.3.0 snapshots, including Zstandard storage.
use crate::{
    common::{self, Context},
    spool::Spool,
    sqlite as q, Result,
};
use rusqlite::Connection;
use serde_json::{json, Value};
pub(crate) fn stage(_db: &Connection, s: &Spool, id: &str, row: &Value) -> Result<()> {
    if row.get("_gap").is_some() {
        return q::push(s, id, "state", row.clone());
    }
    let thread = q::blob(&row["data"])
        .and_then(|b| match row["data_type"].as_str() {
            Some("json") => Some(b),
            Some("zstd") => q::decompress(&b, s.limit),
            _ => None,
        })
        .and_then(|b| String::from_utf8(b).ok())
        .and_then(|b| asr_core::jsonl::decode(&b).ok());
    let Some(mut thread) = thread else {
        return q::gap(s, id, "unparseable");
    };
    if thread["version"] != "0.3.0" {
        q::diagnostic(s, "unsupported_native_version")?;
        return q::gap(s, id, "not_retained");
    }
    q::update_header(s, id, |h| {
        crate::repository::capture(h, crate::Agent::Zed, &thread);
        if let Some(parent) = thread["subagent_context"]["parent_thread_id"]
            .as_str()
            .or_else(|| row["parent_id"].as_str())
        {
            h["parent"] =
                json!({"kind":"subagent","session":q::reference(h,crate::Agent::Zed,parent)});
        }
    })?;
    if let Some(Value::Array(messages)) = thread.as_object_mut().and_then(|o| o.remove("messages"))
    {
        for m in messages {
            q::push(s, id, "message", m)?;
        }
    }
    q::push(s, id, "state", thread)
}
fn parts(content: &Value) -> Vec<Value> {
    content
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|p| {
            if let Some(text) = p["Text"].as_str() {
                Some(common::text(text))
            } else if let Some(t) = p.get("Thinking") {
                let r = common::reasoning(t["text"].as_str(), None);
                Some(r)
            } else if p.get("RedactedThinking").is_some() {
                Some(json!({"type":"reasoning","visibility":"encrypted"}))
            } else {
                None
            }
        })
        .collect()
}
pub(crate) fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if q::common(s, c, v)? {
        return Ok(());
    }
    let d = &v["data"];
    if v["table"] == "state" {
        q::state(s, c, d)?;
        let u = &d["cumulative_token_usage"];
        if u.is_object() {
            let mut u = u.clone();
            for k in [
                "input_tokens",
                "output_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
            ] {
                if u.get(k).is_none() {
                    u[k] = json!(0);
                }
            }
            c.info(s,json!({"type":"session_info","usage":q::usage(&u,"input_tokens","output_tokens","cache_read_input_tokens","cache_creation_input_tokens",false)}))?;
        }
    } else if let Some(compaction) = d.get("Compaction") {
        if let Some(summary) = compaction["Summary"].as_str() {
            c.emit(s,json!({"type":"message","role":"user","author":"harness","origin":"compaction","content":[common::text(summary)]}),None,None)?;
        }
        c.emit(s,json!({"type":"gap","reason":"not_retained","detail":"The saved compaction does not retain its earlier context."}),None,None)?;
    } else {
        let (body, role) = if let Some(body) = d.get("User") {
            (body, "user")
        } else if let Some(body) = d.get("Agent") {
            (body, "assistant")
        } else {
            return q::vendor(s, c, v);
        };
        let mut r = json!({"type":"message","role":role,"content":parts(&body["content"])});
        if role == "assistant" {
            r["author"] = json!("model");
        }
        c.emit(s, r, body["id"].as_str(), None)?;
        for tool in body["content"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|p| p.get("ToolUse"))
        {
            let input = tool["input"].get("value").unwrap_or(&tool["input"]);
            q::call(
                s,
                c,
                tool["id"].as_str(),
                tool["name"].as_str(),
                Some(input),
                None,
                None,
            )?;
        }
        for (id, result) in body["tool_results"].as_object().into_iter().flatten() {
            let content = if result["content"].is_string() {
                common::parts(&result["content"], c.agent)
            } else {
                parts(&result["content"])
            };
            q::result(
                s,
                c,
                Some(id),
                q::error_status(&result["is_error"]),
                Some(json!(content)),
                None,
            )?;
        }
    }
    q::vendor(s, c, v)
}
