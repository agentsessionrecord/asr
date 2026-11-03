//! Kiro legacy and UUID conversation snapshots.
use crate::{
    common::{self, Context},
    spool::Spool,
    sqlite as q, Agent, Error, Result, Summary,
};
use rusqlite::Connection;
use serde_json::{json, Value};
use std::path::Path;
pub(crate) fn stage(
    db: &Connection,
    s: &Spool,
    namespace: Option<&str>,
    path: &Path,
    summary: &mut Summary,
) -> Result<()> {
    let mut found = false;
    for table in ["conversations_v2", "conversations"] {
        if !q::has(db, table)? {
            continue;
        }
        found = true;
        q::rows(
            db,
            table,
            None,
            &["key", "conversation_id"],
            s.limit,
            |row| {
                let body = q::parse(&row["value"]);
                let uuid = row["conversation_id"]
                    .as_str()
                    .or_else(|| body.as_ref().and_then(|d| d["conversation_id"].as_str()));
                if uuid.is_none() && table == "conversations" && namespace.is_none() {
                    return Err(Error::Invalid(
                        "directory-keyed Kiro conversations require --namespace".into(),
                    ));
                }
                let id = uuid.or_else(|| {
                    (table == "conversations")
                        .then(|| row["key"].as_str())
                        .flatten()
                });
                let Some(id) = id.filter(|s| !s.is_empty()).map(str::to_owned) else {
                    q::diagnostic(s, "unidentified_source")?;
                    return Ok(());
                };
                if let Err(error) = q::owner(s, &id, path) {
                    if let Error::Session { code, .. } = error {
                        let h = q::header(Agent::Kiro, &id, namespace);
                        summary.diagnostic_for(&q::reference(&h, Agent::Kiro, &id), code);
                        s.db.execute("INSERT OR IGNORE INTO failed_sessions VALUES(?1)", [&id])?;
                        return Ok(());
                    }
                    return Err(error);
                }
                let mut h = q::header(Agent::Kiro, &id, namespace);
                if let Some(cwd) = row["key"].as_str().filter(|s| common::absolute(s)) {
                    h["cwd"] = json!(cwd);
                }
                if let Some(body) = &body {
                    crate::repository::capture(&mut h, Agent::Kiro, body);
                }
                s.session(&id, &h)?;
                if row.get("_gap").is_some() {
                    return q::push(s, &id, "state", row.clone());
                }
                let Some(mut body) = body else {
                    return q::gap(s, &id, "unparseable");
                };
                match body.as_object_mut().and_then(|o| o.remove("history")) {
                    Some(Value::Array(history)) => {
                        for e in history {
                            q::push(s, &id, "entry", e)?;
                        }
                    }
                    Some(_) => q::gap(s, &id, "unparseable")?,
                    None => {}
                }
                q::push(s, &id, "state", body)
            },
        )?;
    }
    if !found {
        q::diagnostic(s, "unsupported_schema")?;
    }
    Ok(())
}
pub(crate) fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if q::common(s, c, v)? {
        return Ok(());
    }
    let d = &v["data"];
    if v["table"] == "state" {
        if let Some(summary) = d["latest_summary"]
            .as_array()
            .and_then(|a| a.first())
            .and_then(Value::as_str)
        {
            c.emit(s,json!({"type":"message","role":"user","author":"harness","origin":"compaction","content":[common::text(summary)]}),None,None)?;
            c.emit(s, json!({"type":"gap","reason":"not_retained"}), None, None)?;
        }
    } else {
        let user = &d["user"]["content"];
        if let Some(prompt) = user
            .pointer("/Prompt/prompt")
            .or_else(|| user.pointer("/CancelledToolUses/prompt"))
            .and_then(Value::as_str)
        {
            let mut content =
                vec![json!({"type":"text","text":prompt,"author":"human","origin":"prompt"})];
            if let Some(context) = d["user"]["additional_context"].as_str() {
                content.push(
                    json!({"type":"text","text":context,"author":"harness","origin":"injected"}),
                );
            }
            let mut r = json!({"type":"message","role":"user","content":content});
            if prompt.ends_with("...content truncated due to length") {
                r["truncated"] = json!(true);
                c.loss("source_truncation");
            }
            c.emit(s, r, None, None)?;
        }
        for result in user
            .pointer("/ToolUseResults/tool_use_results")
            .or_else(|| user.pointer("/CancelledToolUses/tool_use_results"))
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            let status = match result["status"].as_str() {
                Some("Success" | "success") => "completed",
                Some("Error" | "error") => "failed",
                _ => "unknown",
            };
            let content: Vec<_> = result["content"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|b| b["Text"].as_str().map(common::text))
                .collect();
            q::result(
                s,
                c,
                result["tool_use_id"].as_str(),
                status,
                Some(json!(content)),
                None,
            )?;
        }
        let req = &d["request_metadata"];
        let inf = if req.is_object() {
            Some(
                req["request_id"]
                    .as_str()
                    .map(str::to_owned)
                    .unwrap_or_else(|| {
                        asr_core::identity::derive_id(&[
                            &c.session,
                            &c.ordinal.to_string(),
                            "request",
                        ])
                    }),
            )
        } else {
            None
        };
        if let Some(a) = d["assistant"]
            .get("Response")
            .or_else(|| d["assistant"].get("ToolUse"))
        {
            let mut r = json!({"type":"message","role":"assistant","author":"model","content":common::parts(&a["content"],c.agent)});
            if let Some(inf) = &inf {
                r["inferenceId"] = json!(inf);
            }
            c.emit(s, r, a["message_id"].as_str(), None)?;
            for t in a
                .get("tool_uses")
                .or_else(|| a.get("toolUses"))
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
            {
                q::call(
                    s,
                    c,
                    t["id"].as_str(),
                    t["name"].as_str(),
                    t.get("args"),
                    None,
                    inf.as_deref(),
                )?;
            }
        }
        if let Some(inf) = inf {
            let mut r = json!({"type":"inference"});
            if let Some(model) = req["model_id"].as_str() {
                r["model"] = json!({"requested":model});
            }
            q::stamp(&mut r, &req["stream_end_timestamp_ms"], true);
            if let (Some(start), Some(end)) = (
                q::count(&req["request_start_timestamp_ms"]),
                q::count(&req["stream_end_timestamp_ms"]),
            ) {
                if let Some(duration) = end.checked_sub(start) {
                    r["durationMs"] = json!(duration);
                }
            }
            c.emit(s, r, Some(&inf), Some(&format!("inference:{inf}")))?;
        }
    }
    q::vendor(s, c, v)
}
