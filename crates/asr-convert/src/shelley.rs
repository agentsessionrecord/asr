//! Shelley sequenced messages, Go content variants and call usage reports.
use crate::{
    common::{self, Context},
    spool::Spool,
    sqlite as q, Result,
};
use rusqlite::{Connection, OptionalExtension};
use serde_json::{json, Value};
pub(crate) fn stage(db: &Connection, s: &Spool, id: &str, row: &Value) -> Result<()> {
    let mut fork_owner = None;
    let mut mixed_fork = false;
    q::rows(
        db,
        "messages",
        Some(("conversation_id", id)),
        &["sequence_id", "message_id"],
        s.limit,
        |mut v| {
            if v.get("_gap").is_none() {
                for field in ["llm_data", "user_data", "usage_data", "other_usage_data"] {
                    if !v[field].is_null() {
                        match q::parse(&v[field]) {
                            Some(d) => v[field] = d,
                            _ => return q::gap(s, id, "unparseable"),
                        }
                    }
                }
                if let Some(original) = v["forked_from_message_id"].as_str() {
                    let owner: Option<String> = db
                        .query_row(
                            "SELECT conversation_id FROM messages WHERE message_id=?1",
                            [original],
                            |r| r.get(0),
                        )
                        .optional()?;
                    if let Some(owner) = owner {
                        if fork_owner.as_ref().is_some_and(|old| old != &owner) {
                            mixed_fork = true;
                        }
                        fork_owner = Some(owner.clone());
                        v["_copySession"] = json!(owner);
                    }
                }
            }
            q::push(s, id, "message", v)
        },
    )?;
    q::update_header(s, id, |h| {
        if let Some(parent) = row["parent_conversation_id"].as_str() {
            h["parent"] =
                json!({"kind":"subagent","session":q::reference(h,crate::Agent::Shelley,parent)});
        } else if let Some(parent) = fork_owner.filter(|_| !mixed_fork) {
            h["parent"] =
                json!({"kind":"fork","session":q::reference(h,crate::Agent::Shelley,&parent)});
        }
    })?;
    q::push(s, id, "state", row.clone())
}
fn kind(p: &Value) -> Option<u64> {
    p["Type"].as_u64().or_else(|| match p["Type"].as_str()? {
        "text" | "ContentTypeText" => Some(2),
        "thinking" | "ContentTypeThinking" => Some(3),
        "redacted_thinking" | "ContentTypeRedactedThinking" => Some(4),
        "tool_use" | "ContentTypeToolUse" => Some(5),
        "tool_result" | "ContentTypeToolResult" => Some(6),
        _ => None,
    })
}
fn parts(content: &Value) -> Vec<Value> {
    content
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|p| match kind(p) {
            Some(2) => {
                if let Some(mime) = p["MediaType"].as_str().filter(|s| !s.is_empty()) {
                    Some(json!({"type":"image","mimeType":mime,"data":p["Data"]}))
                } else {
                    p["Text"].as_str().map(common::text)
                }
            }
            Some(3) => {
                let r = common::reasoning(p["Thinking"].as_str(), None);
                Some(r)
            }
            Some(4) => Some(json!({"type":"reasoning","visibility":"encrypted"})),
            _ => None,
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
        return q::vendor(s, c, v);
    }
    if let Some(owner) = d["_copySession"].as_str() {
        c.source["copiedFrom"] = json!({"session":asr_core::identity::session_ref(c.agent.name(),c.namespace.as_deref(),owner)});
    }
    let body = &d["llm_data"];
    let kind_message = d["type"].as_str().unwrap_or("");
    let notice = matches!(
        kind_message,
        "gitinfo" | "modelchange" | "error" | "warning"
    );
    if kind_message == "modelchange" {
        let mut settings = json!({});
        if let Some(effort) = d["user_data"]["reasoning_to"].as_str() {
            settings["modelSettings"] = json!({"reasoningEffort":effort});
        }
        c.settings(s, settings)?;
    }
    let role = if kind_message == "system" {
        Some("system")
    } else {
        match body["Role"].as_i64() {
            Some(0) => Some("user"),
            Some(1) => Some("assistant"),
            _ => body["Role"]
                .as_str()
                .filter(|r| matches!(*r, "user" | "assistant" | "system")),
        }
    };
    let inference = if matches!(kind_message, "agent" | "slug") && d["usage_data"].is_object() {
        Some(asr_core::identity::derive_id(&[
            &c.session,
            d["message_id"].as_str().unwrap_or(""),
            "inference",
        ]))
    } else {
        None
    };
    if let Some(role) = role.filter(|_| !notice) {
        let mut m = json!({"type":"message","role":role,"content":parts(&body["Content"])});
        if role == "assistant" && kind_message == "agent" {
            m["author"] = json!("model");
        }
        if role == "system" {
            m["origin"] = json!("instructions");
        }
        if body["EndOfTurn"] == true {
            m["phase"] = json!("final");
        }
        if let Some(id) = &inference {
            m["inferenceId"] = json!(id);
        }
        q::stamp(&mut m, &d["created_at"], false);
        c.emit(s, m, d["message_id"].as_str(), None)?;
    }
    if !notice {
        for p in body["Content"].as_array().into_iter().flatten() {
            match kind(p) {
                Some(5) => q::call(
                    s,
                    c,
                    p["ID"].as_str(),
                    p["ToolName"].as_str(),
                    p.get("ToolInput"),
                    None,
                    inference.as_deref(),
                )?,
                Some(6) => {
                    let mut r = json!({"type":"tool_result","status":q::error_status(&p["ToolError"]),"content":parts(&p["ToolResult"])});
                    if let Some(call) = p["ToolUseID"].as_str() {
                        r["callId"] = json!(call);
                    }
                    q::stamp(&mut r, &p["ToolUseEndTime"], false);
                    q::receipt(s, c, r, None, None)?;
                }
                _ => {}
            }
        }
    }
    if let Some(id) = inference {
        emit_inference(s, c, &id, &d["usage_data"])?;
    }
    for (i, u) in d["other_usage_data"]
        .as_array()
        .into_iter()
        .flatten()
        .enumerate()
    {
        let id = asr_core::identity::derive_id(&[
            &c.session,
            d["message_id"].as_str().unwrap_or(""),
            "other-usage",
            &i.to_string(),
        ]);
        emit_inference(s, c, &id, u)?;
    }
    q::vendor(s, c, v)
}
fn emit_inference(s: &Spool, c: &mut Context, id: &str, u: &Value) -> Result<()> {
    let mut r = json!({"type":"inference","usage":q::usage(u,"input_tokens","output_tokens","cache_read_input_tokens","cache_creation_input_tokens",false)});
    if let Some(model) = u["model"].as_str() {
        r["model"] = json!({"id":model});
    }
    if let Some(cost) = q::cost(&u["cost_usd"], "harness_estimated") {
        r["cost"] = cost;
    }
    q::stamp(&mut r, &u["end_time"], false);
    c.emit(s, r, Some(id), Some(&format!("inference:{id}")))
}
