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
        Some("user.message" | "assistant.message") => {
            let user = v["type"] == "user.message";
            let inf = string(&d["apiCallId"]);
            if !user {
                if let Some(id) = inf {
                    let mut r = json!({});
                    if let Some(m) = d["model"].as_str() {
                        r["model"] = json!({"id":m});
                    }
                    inference(s, c, id, r)?;
                }
            }
            let body = d
                .get("transformedContent")
                .or_else(|| d.get("content"))
                .unwrap_or(&Value::Null);
            let mut content = parts(body, c);
            if let Some(t) = d["reasoningText"].as_str() {
                content.insert(0, crate::common::reasoning(Some(t), None));
            }
            let mut r = json!({"type":"message","role":if user {"user"} else {"assistant"},"content":content});
            if !user {
                r["author"] = json!("model");
            } else if d["source"]
                .as_str()
                .is_some_and(|v| v.starts_with("schedule-"))
            {
                r["author"] = json!("harness");
                r["origin"] = json!("scheduled");
            } else if d["isAutopilotContinuation"] == true {
                r["author"] = json!("harness");
                r["origin"] = json!("injected");
            }
            if let Some(id) = inf {
                r["inferenceId"] = json!(id);
            }
            let message_id = string(&d["messageId"]).or_else(|| native_id(v));
            let mut fold = None;
            if !user && d["chunkIndex"].is_number() {
                if let Some(id) = message_id {
                    let key = format!("copilot-message:{id}");
                    let mut chunks = s.entity(&key)?.unwrap_or(json!({"text":"","reasoning":""}));
                    for (key, source) in [("text", body), ("reasoning", &d["reasoningText"])] {
                        if let Some(t) = source.as_str() {
                            let previous = chunks[key].as_str().unwrap_or("");
                            if previous.len() + t.len() <= s.limit / 2 {
                                chunks[key] = json!(format!("{previous}{t}"));
                            } else {
                                r["truncated"] = json!(true);
                                c.loss("record_size_limit");
                            }
                        }
                    }
                    r["content"] = json!([]);
                    if let Some(t) = chunks["reasoning"].as_str().filter(|t| !t.is_empty()) {
                        r["content"]
                            .as_array_mut()
                            .unwrap()
                            .push(crate::common::reasoning(Some(t), None));
                    }
                    r["content"]
                        .as_array_mut()
                        .unwrap()
                        .push(json!({"type":"text","text":chunks["text"]}));
                    s.save(&key, &chunks)?;
                    fold = Some(key);
                }
            }
            c.emit(s, r, message_id, fold.as_deref())?;
            for t in d["toolRequests"].as_array().into_iter().flatten() {
                let id = string(&t["toolCallId"]);
                call(
                    s,
                    c,
                    id,
                    t["name"].as_str(),
                    t.get("arguments"),
                    true,
                    None,
                    id.map(|i| format!("copilot-call:{i}")).as_deref(),
                    inf,
                )?;
            }
        }
        Some("tool.execution_start") => {
            let id = string(&d["toolCallId"]);
            let previous = id
                .map(|id| s.entity(&format!("call:{id}")))
                .transpose()?
                .flatten();
            let seen = id
                .map(|id| s.entity(&format!("copilot-start:{id}")))
                .transpose()?
                .flatten()
                .is_some();
            if let Some(id) = id {
                s.save(&format!("copilot-start:{id}"), &json!(true))?;
            }
            let inf = previous.as_ref().and_then(|r| string(&r["inferenceId"]));
            let fold = if seen {
                None
            } else {
                id.map(|id| format!("copilot-call:{id}"))
            };
            call(
                s,
                c,
                id,
                d["toolName"].as_str(),
                d.get("arguments"),
                previous.is_some() && !seen,
                native_id(v),
                fold.as_deref(),
                inf,
            )?;
        }
        Some("tool.execution_complete") => {
            let mut r = json!({"type":"tool_result","status":match d["success"].as_bool(){Some(true)=>"completed",Some(false)=>"failed",None=>"unknown"}});
            copy(&mut r, "callId", d, "toolCallId");
            if let Some(b) = d["result"].get("content") {
                r["content"] = json!(parts(b, c));
            }
            if let Some(code) = d["shellExecution"]["exitCode"].as_i64() {
                r["exec"]["exitCode"] = json!(code);
            }
            if let Some(error) = d["error"].as_str() {
                r["error"] = json!({"message":error});
            }
            if d["result"]["detailedContent"].is_string() {
                meta(c, &mut r, "displayContent", &d["result"]["detailedContent"]);
            }
            c.result(s, r)?;
        }
        Some("assistant.usage") => {
            if let Some(id) = string(&d["apiCallId"]) {
                let mut r = json!({});
                if let Some(m) = d["model"].as_str() {
                    r["model"] = json!({"id":m});
                    copy(&mut r["model"], "provider", d, "modelProvider");
                }
                // Native inputTokens does not establish whether cache tokens are included.
                let mut u = usage(
                    d,
                    [
                        "not-recorded",
                        "outputTokens",
                        "cacheReadTokens",
                        "cacheWriteTokens",
                        "reasoningTokens",
                    ],
                    false,
                );
                u.as_object_mut().unwrap().remove("inputTokens");
                if u != json!({}) {
                    r["usage"] = u;
                }
                if d.get("inputTokens").is_some() {
                    c.loss("usage.input_inclusion");
                    meta(c, &mut r, "nativeUsage", d);
                }
                if let Some(n) = count(&d["duration"]) {
                    r["durationMs"] = json!(n);
                }
                copy(&mut r, "stopReason", d, "finishReason");
                if let Some(e) = d["reasoningEffort"].as_str() {
                    r["settings"] = json!({"reasoningEffort":e});
                }
                inference(s, c, id, r)?;
            }
        }
        Some("session.start" | "session.model_change" | "session.mode_changed") => {
            let mut settings = json!({});
            if let Some(m) = d["newModel"]
                .as_str()
                .or_else(|| d["selectedModel"].as_str())
            {
                meta(c, &mut settings, "requestedModel", &json!(m));
            }
            copy(&mut settings, "mode", d, "mode");
            if let Some(e) = d["reasoningEffort"].as_str() {
                settings["modelSettings"] = json!({"reasoningEffort":e});
            }
            c.settings(s, settings)?;
        }
        Some("permission.requested") => {
            if let Some(id) = string(&d["requestId"]) {
                s.save(&format!("permission:{id}"), d)?;
            }
        }
        Some("permission.completed") => {
            let request = string(&d["requestId"])
                .map(|id| s.entity(&format!("permission:{id}")))
                .transpose()?
                .flatten();
            let call = string(&d["toolCallId"]).or_else(|| {
                request
                    .as_ref()
                    .and_then(|r| string(&r["permissionRequest"]["toolCallId"]))
            });
            let mut decision = d["result"].clone();
            match decision["kind"].as_str() {
                Some("approved-read-only-for-session") => {
                    decision["kind"] = json!("approved-for-session");
                }
                Some("denied-interactively-by-user" | "denied-by-rules") => {
                    decision["kind"] = json!("denied");
                }
                _ => {}
            }
            let by = match d["decisionSource"].as_str() {
                Some("human_response") => Some("user"),
                Some("hook") => Some("hook"),
                Some("host_policy") => Some("policy"),
                _ => None,
            };
            approval(s, c, &decision, call, native_id(v), by)?;
        }
        Some("session.compaction_complete") => {
            compaction(s, c, d.get("summaryContent"), d["historyRetained"] == false)?
        }
        Some("session.truncation") => compaction(s, c, None, true)?,
        Some("system.message" | "instruction.update") => {
            let mut r = json!({"type":"message","role":"system","author":"harness","origin":"instructions","content":parts(&d["content"],c)});
            meta(c, &mut r, "native", d);
            c.emit(s, r, native_id(v), None)?;
        }
        Some("session.shutdown") => {
            if let Some(t) = d.get("endedAt").and_then(time) {
                c.info(s, json!({"type":"session_info","endedAt":t}))?;
            }
        }
        _ => {}
    }
    Ok(())
}
