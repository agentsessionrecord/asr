use super::helpers::*;
use crate::{
    common::{copy, Context},
    spool::Spool,
    Result,
};
use serde_json::{json, Value};
pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    match v["type"].as_str() {
        Some("llm.request") => {
            let id =
                asr_core::identity::derive_id(&[&c.session, "request", &c.ordinal.to_string()]);
            let mut r = json!({});
            if let Some(m) = v["model"].as_str() {
                r["model"] = json!({"requested":m});
                copy(&mut r["model"], "provider", v, "provider");
            }
            for (to, from) in [
                ("reasoningEffort", "thinkingEffort"),
                ("temperature", "temperature"),
                ("maxOutputTokens", "maxTokens"),
            ] {
                if let Some(x) = v.get(from) {
                    if !x.is_null() && (x.is_number() || x.is_string() && to == "reasoningEffort") {
                        r["settings"][to] = x.clone();
                    }
                }
            }
            if let Some(step) = string(&v["turnStep"]) {
                s.save(
                    &format!("kimi-request:{step}"),
                    &json!({"id":id,"record":r}),
                )?;
            }
            inference(s, c, &id, r)?;
        }
        Some("context.append_message") => {
            let m = &v["message"];
            if m["role"] == "tool" {
                let mut r = json!({"type":"tool_result","status":status(&m["isError"])});
                copy(&mut r, "callId", m, "toolCallId");
                meta(c, &mut r, "persistedResult", m);
                c.result(s, r)?;
            } else if let Some(role) = m["role"].as_str() {
                let mut r = json!({"type":"message","role":role,"content":parts(&m["content"],c)});
                match m["origin"]["kind"].as_str() {
                    Some("user") => {
                        r["author"] = json!("human");
                        r["origin"] = json!("prompt");
                    }
                    Some("hook_result") => {
                        r["author"] = json!("hook");
                        r["origin"] = json!("injected");
                    }
                    Some("cron_job" | "cron_missed") => {
                        r["author"] = json!("harness");
                        r["origin"] = json!("scheduled");
                    }
                    Some("compaction_summary") => {
                        r["author"] = json!("harness");
                        r["origin"] = json!("compaction");
                    }
                    Some("background_task" | "system_trigger" | "injection" | "retry") => {
                        r["author"] = json!("harness");
                        r["origin"] = json!("injected");
                    }
                    _ => {}
                }
                if role == "assistant" {
                    r["author"] = json!("model");
                }
                if matches!(role, "user" | "assistant" | "system" | "developer") {
                    c.emit(s, r, native_id(m), None)?;
                }
                for t in m["toolCalls"].as_array().into_iter().flatten() {
                    call(
                        s,
                        c,
                        string(&t["id"]),
                        t["name"].as_str(),
                        t.get("arguments"),
                        true,
                        None,
                        None,
                        None,
                    )?;
                }
            }
        }
        Some("context.append_loop_event") => {
            let e = &v["event"];
            let step = e["turnId"]
                .as_str()
                .zip(e["step"].as_u64())
                .map(|(t, n)| format!("{t}.{n}"));
            let request = step
                .as_deref()
                .map(|k| s.entity(&format!("kimi-request:{k}")))
                .transpose()?
                .flatten();
            let inf = request.as_ref().and_then(|r| string(&r["id"]));
            match e["type"].as_str() {
                Some("step.end") => {
                    let id = inf.map(str::to_owned).unwrap_or_else(|| {
                        asr_core::identity::derive_id(&[
                            &c.session,
                            "step",
                            e["uuid"].as_str().unwrap_or(&c.ordinal.to_string()),
                        ])
                    });
                    let mut r = request
                        .as_ref()
                        .map(|r| r["record"].clone())
                        .unwrap_or(json!({}));
                    let u = usage(
                        &e["usage"],
                        [
                            "inputOther",
                            "output",
                            "inputCacheRead",
                            "inputCacheCreation",
                            "reasoning",
                        ],
                        true,
                    );
                    if u != json!({}) {
                        r["usage"] = u;
                    }
                    copy(&mut r, "stopReason", e, "rawFinishReason");
                    inference(s, c, &id, r)?;
                }
                Some("tool.call") => call(
                    s,
                    c,
                    string(&e["toolCallId"]),
                    e["name"].as_str().or_else(|| e["toolName"].as_str()),
                    e.get("args").or_else(|| e.get("input")),
                    true,
                    native_id(e),
                    None,
                    inf,
                )?,
                Some("tool.result") => {
                    let out = e.get("result").unwrap_or(e);
                    let mut r = json!({"type":"tool_result","status":if out["isError"]==true {"failed"}else if out["isError"]==false {"completed"} else {"unknown"}});
                    copy(&mut r, "callId", e, "toolCallId");
                    meta(c, &mut r, "persistedResult", out);
                    if out["truncated"] == true {
                        r["truncated"] = json!(true);
                        c.loss("tool_output");
                    }
                    c.result(s, r)?;
                }
                Some("content.part") => {
                    let p = &e["part"];
                    let body = parts(&json!([p]), c);
                    if let Some(step) = string(&e["stepUuid"]) {
                        let key = format!("kimi-content:{step}");
                        let old = s.entity(&key)?.unwrap_or(json!([]));
                        let mut body = body;
                        let mut assembled = old.as_array().cloned().unwrap_or_default();
                        for p in body.drain(..) {
                            if let Some(last) = assembled.last_mut().filter(|last| {
                                last["type"] == p["type"]
                                    && last["text"].is_string()
                                    && p["text"].is_string()
                                    && last["visibility"] == p["visibility"]
                                    && matches!(p["type"].as_str(), Some("text" | "reasoning"))
                            }) {
                                if let (Some(a), Some(b)) =
                                    (last["text"].as_str(), p["text"].as_str())
                                {
                                    last["text"] = json!(format!("{a}{b}"));
                                }
                            } else {
                                assembled.push(p);
                            }
                        }
                        let mut r = json!({"type":"message","role":"assistant","author":"model"});
                        if serde_json::to_vec(&assembled)?.len() <= s.limit / 2 {
                            s.save(&key, &json!(assembled))?;
                            r["content"] = json!(assembled);
                        } else {
                            r["content"] = old;
                            r["truncated"] = json!(true);
                            c.loss("record_size_limit");
                        }
                        if let Some(i) = inf {
                            r["inferenceId"] = json!(i);
                        }
                        c.emit(s, r, None, Some(&key))?;
                    }
                }
                _ => {}
            }
        }
        Some("context.apply_compaction") => compaction(
            s,
            c,
            v.get("contextSummary").or_else(|| v.get("summary")),
            true,
        )?,
        Some("permission.record_approval_result") => approval(
            s,
            c,
            &v["result"],
            string(&v["toolCallId"]),
            native_id(v),
            None,
        )?,
        Some("permission.set_mode") => {
            let mut settings = json!({});
            if let Some(mode) = v.get("mode") {
                settings["approval"] = mode.clone();
            }
            c.settings(s, settings)?;
        }
        Some("config.update" | "profile.bind") => {
            let mut settings = json!({});
            if let Some(mode) = v["profileName"].as_str() {
                settings["mode"] = json!(mode);
            }
            for (to, from) in [
                ("reasoningEffort", "thinkingEffort"),
                ("temperature", "temperature"),
                ("maxOutputTokens", "maxTokens"),
            ] {
                if let Some(x) = v.get(from) {
                    settings["modelSettings"][to] = x.clone();
                }
            }
            c.settings(s, settings)?;
            if let Some(prompt) = v["systemPrompt"].as_str() {
                c.emit(s,json!({"type":"message","role":"system","author":"harness","origin":"instructions","content":[{"type":"text","text":prompt}]}),None,None)?;
            }
        }
        Some("llm.tools_snapshot") => tools(s, c, &v["tools"])?,
        _ => {}
    }
    Ok(())
}
