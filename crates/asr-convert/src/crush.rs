//! Crush message parts and current session totals.
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
        "messages",
        Some(("session_id", id)),
        &["created_at", "id"],
        s.limit,
        |mut v| {
            if v.get("_gap").is_none() {
                match q::parse(&v["parts"]) {
                    Some(p) if p.is_array() => v["parts"] = p,
                    _ => return q::gap(s, id, "unparseable"),
                }
            }
            q::push(s, id, "messages", v)
        },
    )?;
    for table in ["files", "read_files"] {
        q::rows(
            db,
            table,
            Some(("session_id", id)),
            &["path", "version", "id"],
            s.limit,
            |v| q::push(s, id, table, v),
        )?;
    }
    q::push(s, id, "sessions", row.clone())
}
pub(crate) fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if q::common(s, c, v)? {
        return Ok(());
    }
    let d = &v["data"];
    if v["table"] == "sessions" {
        q::state(s, c, d)?;
        // Zero-initialized counters do not prove a provider report occurred.
        if ["prompt_tokens", "completion_tokens", "cost"]
            .iter()
            .any(|k| d[*k].as_f64().is_some_and(|n| n > 0.0))
        {
            let mut info = json!({"type":"session_info","usage":q::usage(d,"prompt_tokens","completion_tokens","","",true)});
            if let Some(cost) = q::cost(&d["cost"], "harness_estimated") {
                info["cost"] = cost;
            }
            c.info(s, info)?;
        }
    } else if v["table"] == "messages" {
        let mut content = Vec::new();
        let mut status = None;
        for p in d["parts"].as_array().into_iter().flatten() {
            match p["type"].as_str() {
                Some("text") => {
                    if let Some(text) = p["data"]["text"].as_str() {
                        content.push(common::text(text));
                    }
                }
                Some("reasoning") => {
                    let r = common::reasoning(p["data"]["thinking"].as_str(), None);
                    content.push(r);
                }
                Some("finish") => {
                    status = match p["data"]["reason"].as_str() {
                        Some("end_turn" | "stop" | "tool_use") => Some("complete"),
                        Some("max_tokens" | "canceled") => Some("interrupted"),
                        Some("error") => Some("error"),
                        _ => None,
                    }
                }
                Some("image_url") => {
                    if let Some(uri) = p["data"]["url"].as_str() {
                        content.push(json!({"type":"resource_link","uri":uri,"name":"image"}));
                    }
                }
                Some("binary") => {
                    if let Some(mime) = p["data"]["MIMEType"].as_str() {
                        content
                            .push(json!({"type":"image","mimeType":mime,"data":p["data"]["Data"]}));
                    }
                }
                _ => {}
            }
        }
        let role = d["role"].as_str().unwrap_or("");
        if matches!(role, "user" | "assistant" | "system" | "developer") {
            let mut m = json!({"type":"message","role":role,"content":content});
            if role == "assistant" {
                m["author"] = json!("model");
            }
            if let Some(status) = status {
                m["status"] = json!(status);
            }
            if d["is_summary_message"] == 1 || d["is_summary_message"] == true {
                m["author"] = json!("harness");
                m["origin"] = json!("compaction");
            }
            q::stamp(&mut m, &d["created_at"], true);
            c.emit(s, m, d["id"].as_str(), None)?;
            if d["is_summary_message"] == 1 || d["is_summary_message"] == true {
                c.emit(s,json!({"type":"gap","reason":"not_retained","detail":"The retained summary does not identify the earlier history."}),None,None)?;
            }
        }
        for p in d["parts"].as_array().into_iter().flatten() {
            let b = &p["data"];
            match p["type"].as_str() {
                Some("tool_call") => q::call(
                    s,
                    c,
                    b["id"].as_str(),
                    b["name"].as_str(),
                    b.get("input"),
                    None,
                    None,
                )?,
                Some("tool_result") => q::result(
                    s,
                    c,
                    b["tool_call_id"].as_str(),
                    q::error_status(&b["is_error"]),
                    b["content"].as_str().map(|t| json!([common::text(t)])),
                    None,
                )?,
                Some("shell_command") => {
                    let id = asr_core::identity::derive_id(&[
                        &c.session,
                        &c.ordinal.to_string(),
                        &c.slot.to_string(),
                        "shell",
                    ]);
                    let mut call = json!({"type":"tool_call","callId":id,"name":"shell_command","kind":"execute","requestedBy":"user"});
                    if let Some(cmd) = b.get("command") {
                        call["input"] = json!({"command":cmd});
                    }
                    c.emit(s, call, None, None)?;
                    let mut r =
                        json!({"type":"tool_result","callId":id,"status":"unknown","exec":{}});
                    common::copy(&mut r["exec"], "command", b, "command");
                    common::copy(&mut r["exec"], "output", b, "output");
                    if b["exit_code"].as_i64().is_some() {
                        r["exec"]["exitCode"] = b["exit_code"].clone();
                    }
                    q::receipt(s, c, r, None, None)?;
                }
                _ => {}
            }
        }
    }
    q::vendor(s, c, v)
}
