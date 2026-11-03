use super::helpers::*;
use crate::{
    common::{copy, Context},
    spool::Spool,
    Result,
};
use serde_json::{json, Value};
pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    let d = &v["data"];
    match v["type"].as_str() {
        Some("request/header") => {
            let h = &d["header"];
            s.save("deepseek-request", &h["config"])?;
            if let Some(t) = h["system"].as_str() {
                c.emit(s,json!({"type":"message","role":"system","author":"harness","origin":"instructions","content":[{"type":"text","text":t}]}),None,None)?;
            }
            tools(s, c, &h["tools"])?;
            let mut settings = json!({});
            for (to, from) in [
                ("reasoningEffort", "reasoningEffort"),
                ("temperature", "temperature"),
                ("maxOutputTokens", "maxTokens"),
            ] {
                if let Some(x) = h["config"].get(from) {
                    settings["modelSettings"][to] = x.clone();
                }
            }
            c.settings(s, settings)?;
        }
        Some("step/start") => {
            s.save("deepseek-response", &Value::Null)?;
            s.save("deepseek-usage", &Value::Null)?;
        }
        Some("assistant/chunk") => {
            let chunk = &d["chunk"];
            if chunk["type"] == "usage" {
                s.save("deepseek-usage", &chunk["usage"])?;
            }
            if chunk["type"] == "finish" {
                let id =
                    asr_core::identity::derive_id(&[&c.session, "request", &v["seq"].to_string()]);
                s.save("deepseek-response", &json!(id))?;
                let mut r = request(s)?;
                if let Some(u) = s.entity("deepseek-usage")?.filter(Value::is_object) {
                    r["usage"] = usage(
                        &u,
                        [
                            "inputTokens",
                            "outputTokens",
                            "cacheReadTokens",
                            "cacheWriteTokens",
                            "reasoningTokens",
                        ],
                        true,
                    );
                }
                if let Some(reason) = chunk["reason"]["kind"].as_str() {
                    r["stopReason"] = json!(reason);
                }
                inference(s, c, &id, r)?;
            }
        }
        Some(
            "system/message" | "developer/message" | "user/message" | "assistant/message"
            | "tool/result",
        ) => {
            let kind = v["type"].as_str().unwrap();
            let m = if matches!(
                kind,
                "system/message" | "developer/message" | "user/message"
            ) {
                d
            } else {
                &d["message"]
            };
            if v["surfaceOp"]["op"] == "replace" {
                return compaction(s, c, m.get("content"), false);
            }
            let inf = if kind == "assistant/message" {
                // The assembled response identifies one step call. A finish event provides its earlier boundary.
                Some(
                    s.entity("deepseek-response")?
                        .and_then(|v| v.as_str().map(str::to_owned))
                        .unwrap_or_else(|| {
                            asr_core::identity::derive_id(&[
                                &c.session,
                                "response",
                                m["id"].as_str().unwrap_or(&c.ordinal.to_string()),
                            ])
                        }),
                )
            } else {
                None
            };
            if let Some(id) = &inf {
                let mut r = request(s)?;
                if let Some(model) = m["source"]["model"].as_str() {
                    r["model"]["id"] = json!(model);
                    copy(&mut r["model"], "provider", &m["source"], "provider");
                }
                if d["usage"].is_object() {
                    r["usage"] = usage(
                        &d["usage"],
                        [
                            "inputTokens",
                            "outputTokens",
                            "cacheReadTokens",
                            "cacheWriteTokens",
                            "reasoningTokens",
                        ],
                        true,
                    );
                }
                inference(s, c, id, r)?;
            }
            if kind == "tool/result" {
                let block = if m["content"][0]["type"] == "tool-result" {
                    &m["content"][0]
                } else {
                    m
                };
                let id = string(&m["source"]["callId"]).or_else(|| string(&block["toolCallId"]));
                result(s, c, id, status(&block["isError"]), block.get("content"))?;
            } else {
                let role = m["role"]
                    .as_str()
                    .unwrap_or(kind.split('/').next().unwrap());
                let mut r = json!({"type":"message","role":role,"content":parts(&m["content"],c)});
                match m["source"]["kind"].as_str() {
                    Some("user") => {
                        r["author"] = json!("human");
                        r["origin"] = json!("prompt");
                    }
                    Some("model") => r["author"] = json!("model"),
                    Some("plugin" | "goal" | "subagent-settled") => {
                        r["author"] = json!("harness");
                        r["origin"] = json!("injected");
                    }
                    Some("coordinator" | "subagent-report") => {
                        r["author"] = json!("agent");
                        r["origin"] = json!("subagent_report");
                    }
                    _ => {}
                }
                if matches!(role, "system" | "developer") {
                    r["origin"] = json!("instructions");
                }
                if let Some(id) = &inf {
                    r["inferenceId"] = json!(id);
                }
                c.emit(s, r, native_id(m), None)?;
                for t in m["content"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter(|t| t["type"] == "tool-call")
                {
                    let id = string(&t["id"]);
                    call(
                        s,
                        c,
                        id,
                        t["name"].as_str(),
                        t.get("arguments"),
                        true,
                        None,
                        None,
                        inf.as_deref(),
                    )?;
                    if let Some(id) = id {
                        s.save(
                            &format!("deepseek-call:{}:{}:{id}", d["turn"], d["step"]),
                            &json!(true),
                        )?;
                    }
                }
            }
        }
        Some("tool/call") => {
            if let Some(id) = string(&d["callId"]) {
                if s.entity(&format!("deepseek-call:{}:{}:{id}", d["turn"], d["step"]))?
                    .is_none()
                {
                    call(
                        s,
                        c,
                        Some(id),
                        d["name"].as_str(),
                        d.get("arguments"),
                        false,
                        None,
                        None,
                        None,
                    )?;
                }
            }
        }
        Some("compaction/summary") if d["llmStreamCall"] == true => {
            let id =
                asr_core::identity::derive_id(&[&c.session, "compaction", &c.ordinal.to_string()]);
            let mut r = json!({"usage":usage(&d["usage"],["inputTokens","outputTokens","cacheReadTokens","cacheWriteTokens","reasoningTokens"],true)});
            if let Some(m) = d["model"].as_str() {
                r["model"] = json!({"id":m});
            }
            inference(s, c, &id, r)?;
        }
        _ => {}
    }
    Ok(())
}
fn request(s: &Spool) -> Result<Value> {
    let req = s.entity("deepseek-request")?.unwrap_or(json!({}));
    let mut r = json!({});
    if let Some(m) = req["model"].as_str() {
        r["model"] = json!({"requested":m});
        copy(&mut r["model"], "provider", &req, "provider");
    }
    for (to, from) in [
        ("reasoningEffort", "reasoningEffort"),
        ("temperature", "temperature"),
        ("maxOutputTokens", "maxTokens"),
    ] {
        if let Some(x) = req.get(from) {
            r["settings"][to] = x.clone();
        }
    }
    Ok(r)
}
