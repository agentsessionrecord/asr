//! Goose native message blocks and independent usage ledger.
use crate::{
    common::{self, Context},
    spool::Spool,
    sqlite as q, Result,
};
use rusqlite::Connection;
use serde_json::{json, Value};
pub(crate) fn stage(db: &Connection, s: &Spool, id: &str, row: &Value) -> Result<()> {
    let ledger = q::has(db, "usage_ledger")?
        && db.query_row(
            "SELECT EXISTS(SELECT 1 FROM usage_ledger WHERE session_id=?1)",
            [id],
            |r| r.get::<_, bool>(0),
        )?;
    q::rows(
        db,
        "messages",
        Some(("session_id", id)),
        &["created_timestamp", "id"],
        s.limit,
        |mut v| {
            if v.get("_gap").is_some() {
                return q::push(s, id, "message", v);
            }
            let Some(mut content) = q::parse(&v["content_json"]).filter(Value::is_array) else {
                return q::gap(s, id, "unparseable");
            };
            for part in content.as_array_mut().into_iter().flatten() {
                let d = &mut part["data"];
                if d["actionType"] == "elicitation" {
                    let questions: Vec<_> = d["requested_schema"]["properties"]
                        .as_object()
                        .into_iter()
                        .flatten()
                        .filter(|(_, v)| v["format"] == "password" || v["writeOnly"] == true)
                        .map(|(k, _)| json!({"id":k,"secret":true}))
                        .collect();
                    crate::privacy::questions(s, &json!({"questions":questions}))?;
                }
                if d["actionType"] == "elicitationResponse" {
                    d["answers"] = d["user_data"].clone();
                }
            }
            v["content_json"] = content;
            v["metadata_json"] = q::parse(&v["metadata_json"]).unwrap_or(Value::Null);
            v["_hasLedger"] = json!(ledger);
            q::push(s, id, "message", v)
        },
    )?;
    q::rows(
        db,
        "usage_ledger",
        Some(("session_id", id)),
        &["id"],
        s.limit,
        |v| q::push(s, id, "ledger", v),
    )?;
    q::rows(
        db,
        "thread_messages",
        Some(("session_id", id)),
        &["id"],
        s.limit,
        |v| q::push(s, id, "thread_messages", v),
    )?;
    q::push(s, id, "state", row.clone())
}
fn inference(
    s: &Spool,
    c: &mut Context,
    id: &str,
    u: &Value,
    meta: &Value,
    ledger: bool,
) -> Result<()> {
    // Cache inclusion is not established for the ledger. Preserve exact counts as metadata.
    let usage = if ledger {
        q::usage(
            u,
            "",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            true,
        )
    } else {
        q::usage(
            u,
            "",
            "outputTokens",
            "cacheReadTokens",
            "cacheWriteTokens",
            true,
        )
    };
    c.loss("usage_cache_inclusion");
    let mut r = json!({"type":"inference","usage":usage});
    if ledger {
        if let Some(model) = u["model"].as_str() {
            r["model"] = json!({"id":model});
        }
    } else {
        for (native, core) in [("requestedModel", "requested"), ("resolvedModel", "id")] {
            if let Some(model) = meta["inference"][native].as_str() {
                r["model"][core] = json!(model);
            }
        }
    }
    let amount = &u["cost"];
    if let Some(cost) = q::cost(
        amount,
        if u["cost_source"] == "provider_reported" || u["costSource"] == "provider_reported" {
            "provider_reported"
        } else {
            "harness_estimated"
        },
    ) {
        r["cost"] = cost;
    }
    if ledger {
        q::stamp(&mut r, &u["created_timestamp"], false);
    } else if let Some(n) = q::count(&u["elapsedMs"]) {
        r["durationMs"] = json!(n);
    }
    q::metadata(&mut r, c.agent, "usage", u);
    c.emit(s, r, Some(id), Some(&format!("inference:{id}")))
}
pub(crate) fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if q::common(s, c, v)? {
        return Ok(());
    }
    let d = &v["data"];
    if v["table"] == "state" {
        q::state(s, c, d)?;
        if let Some(mode) = d["goose_mode"].as_str() {
            c.settings(s, json!({"mode":mode}))?;
        }
    } else if v["table"] == "ledger" {
        let id = asr_core::identity::derive_id(&[&c.session, "usage-ledger", &d["id"].to_string()]);
        inference(s, c, &id, d, &Value::Null, true)?;
    } else if v["table"] == "message" {
        let meta = &d["metadata_json"];
        let identity = d["message_id"]
            .as_str()
            .map(str::to_owned)
            .unwrap_or_else(|| d["id"].to_string());
        let inf = if d["_hasLedger"] != true && meta["usage"].is_object() {
            Some(asr_core::identity::derive_id(&[
                &c.session,
                &identity,
                "message-usage",
            ]))
        } else {
            None
        };
        let role = d["role"].as_str().unwrap_or("");
        let content: Vec<_> = d["content_json"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|p| match p["type"].as_str() {
                Some("text") => p["text"].as_str().map(common::text),
                Some("thinking") => Some(common::reasoning(p["thinking"].as_str(), None)),
                Some("redactedThinking") => {
                    Some(json!({"type":"reasoning","visibility":"encrypted"}))
                }
                _ => None,
            })
            .collect();
        if matches!(role, "user" | "assistant" | "system" | "developer") {
            let mut r = json!({"type":"message","role":role,"content":content});
            if role == "assistant" {
                r["author"] = json!("model");
            }
            if role == "user" && meta["steer"] == true {
                r["origin"] = json!("queued");
            }
            if meta["turnContext"] == true {
                r["origin"] = json!("injected");
                r["author"] = json!("harness");
            }
            if meta["usage"]["isCompaction"] == true {
                r["origin"] = json!("compaction");
                r["author"] = json!("harness");
            }
            if let Some(inf) = &inf {
                r["inferenceId"] = json!(inf);
            }
            q::stamp(&mut r, &d["created_timestamp"], false);
            c.emit(s, r, d["message_id"].as_str(), None)?;
            if meta["usage"]["isCompaction"] == true {
                c.emit(s, json!({"type":"gap","reason":"not_retained"}), None, None)?;
            }
        }
        for p in d["content_json"].as_array().into_iter().flatten() {
            match p["type"].as_str() {
                Some("toolRequest" | "frontendToolRequest") => {
                    let f = &p["toolCall"]["value"];
                    q::call(
                        s,
                        c,
                        p["id"].as_str(),
                        f["name"].as_str(),
                        f.get("arguments"),
                        None,
                        inf.as_deref(),
                    )?;
                }
                Some("toolResponse") => {
                    let t = &p["toolResult"];
                    let status = if t["status"] == "error" || t["value"]["isError"] == true {
                        "failed"
                    } else if t["status"] == "success" {
                        "completed"
                    } else {
                        "unknown"
                    };
                    q::result(
                        s,
                        c,
                        p["id"].as_str(),
                        status,
                        t["value"]
                            .get("content")
                            .map(|v| json!(common::parts(v, c.agent))),
                        None,
                    )?;
                }
                Some("actionRequired") => {
                    let a = &p["data"];
                    if a["actionType"] == "toolConfirmationResponse" {
                        let decision = match a["permission"].as_str() {
                            Some("always_allow" | "allow_once") => Some("approved"),
                            Some("always_deny" | "deny_once") => Some("denied"),
                            Some("cancel") => Some("cancelled"),
                            _ => None,
                        };
                        if let Some(decision) = decision {
                            let mut r = json!({"type":"approval","decision":decision,"native":a});
                            if let Some(call) = a["id"].as_str() {
                                r["callId"] = json!(call);
                            }
                            if decision != "cancelled"
                                && matches!(
                                    a["permission"].as_str(),
                                    Some("allow_once" | "deny_once")
                                )
                            {
                                r["scope"] = json!("once");
                            }
                            c.emit(s, r, None, None)?;
                        }
                    }
                }
                _ => {}
            }
        }
        if let Some(inf) = inf {
            inference(s, c, &inf, &meta["usage"], meta, false)?;
        }
    }
    q::vendor(s, c, v)
}
