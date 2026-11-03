use super::helpers::*;
use crate::{
    common::{copy, Context},
    spool::Spool,
    Agent, Result,
};
use serde_json::{json, Value};
pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if v["kind"] == "record" && v["type"] == "usage" {
        if matches!(
            v["cause"].as_str(),
            Some("assistant" | "compaction" | "branch_summary" | "deferred_fetch")
        ) {
            if let Some(id) = string(&v["id"]) {
                let mut r = json!({"usage":usage(&v["usage"],["input","output","cacheRead","cacheWrite","reasoning"],true)});
                copy(&mut r, "stopReason", v, "stopReason");
                if let Some(amount) = v["usage"]["cost"]["total"].as_number() {
                    r["cost"] =
                        json!({"amount":amount,"currency":"USD","source":"harness_estimated"});
                }
                inference(s, c, id, r)?;
            }
        }
        return Ok(());
    }
    match v["type"].as_str() {
        Some("message") => message_entry(s, c, v)?,
        Some("custom_message") => {
            c.emit(s,json!({"type":"message","role":"user","author":"harness","origin":"injected","content":parts(&v["content"],c)}),native_id(v),None)?;
        }
        Some("thinking_level_change") => {
            if let Some(e) = v
                .get("thinkingLevel")
                .filter(|e| e.is_string() || e.is_null())
            {
                c.settings(s, json!({"modelSettings":{"reasoningEffort":e}}))?;
            }
        }
        Some("session_info") => {
            if let Some(t) = v["name"].as_str() {
                c.info(s, json!({"type":"session_info","title":t}))?;
            }
        }
        Some("compaction" | "branch_summary") => {
            compaction(s, c, v.get("summary"), v["historyRetained"] == false)?
        }
        _ => {}
    }
    if v["kind"] == "fact" && v["fact"] == "name" && v["name"].is_string() {
        c.info(s, json!({"type":"session_info","title":v["name"]}))?;
    }
    Ok(())
}
pub(super) fn message_entry(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    let m = &v["message"];
    let role = m["role"].as_str().unwrap_or("");
    let open = c.agent == Agent::OpenClaw;
    if role == "toolResult" {
        let id = string(&m["toolCallId"]);
        let mut r = json!({"type":"tool_result","status":status(&m["isError"])});
        if let Some(id) = id {
            r["callId"] = json!(id);
        }
        if let Some(body) = m.get("content") {
            r["content"] = json!(parts(body, c));
        }
        if let Some(code) = m["details"]["exitCode"].as_i64() {
            r["exec"]["exitCode"] = json!(code);
        }
        if m["details"]["truncation"]["truncated"] == true || m["truncated"] == true {
            r["truncated"] = json!(true);
            c.loss("tool_output");
        }
        c.result(s, r)?;
        return Ok(());
    }
    if !matches!(
        role,
        "assistant" | "user" | "system" | "developer" | "custom"
    ) {
        return Ok(());
    }
    let mirror =
        open && (m["provider"] == "openclaw" || m["openclawDeliveryMirror"]["kind"].is_string());
    let inf = (!mirror && role == "assistant")
        .then(|| string(&m["responseId"]))
        .flatten();
    if let Some(id) = inf {
        let mut r = json!({"model":{}});
        copy(&mut r["model"], "requested", m, "model");
        copy(&mut r["model"], "id", m, "responseModel");
        copy(&mut r["model"], "provider", m, "provider");
        let unavailable = m["usageReport"]["state"] == "unavailable";
        let placeholder = matches!(m["stopReason"].as_str(), Some("error" | "aborted"))
            && ["input", "output", "cacheRead", "cacheWrite"]
                .iter()
                .all(|k| count(&m["usage"][*k]).unwrap_or(0) == 0);
        if !unavailable && !placeholder {
            let u = usage(
                &m["usage"],
                ["input", "output", "cacheRead", "cacheWrite", "reasoning"],
                true,
            );
            if u != json!({}) {
                r["usage"] = u;
            }
            if let Some(amount) = m["usage"]["cost"]["total"].as_number() {
                r["cost"] = json!({"amount":amount,"currency":"USD","source":if m["usage"]["cost"]["source"]=="provider-billed" {"provider_reported"}else{"harness_estimated"}});
            }
        }
        copy(&mut r, "stopReason", m, "stopReason");
        inference(s, c, id, r)?;
    }
    let mut r = json!({"type":"message","role":if role=="custom" {"user"}else{role},"content":parts(&m["content"],c)});
    if role == "assistant" {
        r["author"] = json!(if mirror { "harness" } else { "model" });
    }
    if role == "custom"
        || m["synthetic"] == true
        || m["runtimeContext"] == true
        || m["provenance"]["kind"] == "internal_system"
    {
        r["author"] = json!("harness");
        r["origin"] = json!("injected");
    }
    if m["provenance"]["kind"] == "inter_session" {
        r["author"] = json!("agent");
        r["origin"] = json!("subagent_report");
        if let Some(p) = m["provenance"]["originSessionId"].as_str() {
            r["from"] = json!(asr_core::identity::session_ref(c.agent.name(), None, p));
        }
    }
    if open
        && role == "user"
        && m["synthetic"] != true
        && m["runtimeContext"] != true
        && !matches!(
            m["provenance"]["kind"].as_str(),
            Some("internal_system" | "inter_session")
        )
    {
        if let Some(text) = m["__openclaw"]["modelPromptProjection"]["text"].as_str() {
            r["content"] = json!([{"type":"text","text":text}]);
        } else {
            meta(c, &mut r, "displayContent", &m["content"]);
            r["content"] = json!([]);
            c.loss("message_content");
        }
        let sender = &m["__openclaw"]["senderIdentity"];
        if sender["type"] == "profile" || sender["senderKind"] == "human" {
            r["author"] = json!("human");
            r["origin"] = json!("prompt");
        }
    }
    if mirror {
        meta(c, &mut r, "displayContent", &m["content"]);
        r["content"] = json!([]);
        c.loss("message_content");
    }
    if let Some(id) = inf {
        r["inferenceId"] = json!(id);
    }
    match m["stopReason"].as_str() {
        Some("error") => r["status"] = json!("error"),
        Some("aborted") => r["status"] = json!("interrupted"),
        _ => {}
    }
    let native = native_id(v);
    let fold = native.map(|id| format!("message:{id}"));
    c.emit(s, r, native, fold.as_deref())?;
    for (i, t) in m["content"].as_array().into_iter().flatten().enumerate() {
        if t["type"] == "toolCall" {
            let fold = native.map(|id| format!("call-entry:{id}:{i}"));
            call(
                s,
                c,
                string(&t["id"]),
                t["name"].as_str(),
                t.get("arguments"),
                !mirror,
                None,
                fold.as_deref(),
                inf,
            )?;
        }
    }
    Ok(())
}
