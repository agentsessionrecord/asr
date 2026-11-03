use super::helpers::*;
use crate::{
    common::{self, copy, Context},
    spool::Spool,
    Result,
};
use serde_json::{json, Value};
fn update(v: &Value) -> &Value {
    v.pointer("/params/update")
        .or_else(|| v.get("update"))
        .unwrap_or(v)
}
pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    let u = update(v);
    match u["sessionUpdate"].as_str() {
        Some("response_started" | "response_completed") => {
            let started = u["sessionUpdate"] == "response_started";
            let active = s.entity("grok-active")?;
            let id = string(&u["message_id"])
                .map(str::to_owned)
                .or_else(|| {
                    (!started)
                        .then(|| active.as_ref().and_then(|a| a.as_str()).map(str::to_owned))
                        .flatten()
                })
                .unwrap_or_else(|| {
                    asr_core::identity::derive_id(&[&c.session, "response", &c.ordinal.to_string()])
                });
            let mut r = json!({});
            if let Some(m) = u["model"].as_str() {
                r["model"] = json!({"id":m});
            }
            let usage_source = if started { u } else { &u["usage"] };
            let usage = usage(
                usage_source,
                [
                    "input_tokens",
                    "output_tokens",
                    "cache_read_input_tokens",
                    "cache_creation_input_tokens",
                    "reasoning_tokens",
                ],
                true,
            );
            if usage != json!({}) {
                r["usage"] = usage;
            }
            copy(&mut r, "stopReason", u, "stop_reason");
            // A completion can reveal the native provider ID after a generated start ID.
            let old = active.as_ref().and_then(Value::as_str);
            if !started && old.is_some_and(|old| old != id) {
                let old = old.unwrap();
                s.db.execute(
                    "UPDATE projected SET fold=?1,value=json_set(value,'$.id',?2) WHERE fold=?3",
                    rusqlite::params![format!("inference:{id}"), id, format!("inference:{old}")],
                )?;
                s.db.execute("UPDATE projected SET value=json_set(value,'$.inferenceId',?1) WHERE json_extract(value,'$.inferenceId')=?2",rusqlite::params![id,old])?;
            }
            inference(s, c, &id, r)?;
            s.save(
                "grok-active",
                &if started { json!(id) } else { Value::Null },
            )?;
        }
        Some("user_message_chunk" | "agent_message_chunk" | "agent_thought_chunk") => {
            let kind = u["sessionUpdate"].as_str().unwrap();
            if kind == "user_message_chunk" {
                s.save("grok-active", &Value::Null)?;
            }
            let boundary = json!([
                kind,
                u["messageId"],
                u["_meta"]["promptIndex"],
                v.pointer("/params/_meta/promptId")
                    .or_else(|| v.pointer("/_meta/promptId"))
            ]);
            let last = s.entity("grok-chunks")?;
            let same = last.as_ref().is_some_and(|l| {
                l["boundary"] == boundary && l["ordinal"].as_u64() == Some(c.ordinal - 1)
            });
            let key = if same {
                last.as_ref().unwrap()["key"].as_str().unwrap().to_owned()
            } else {
                format!("grok-message:{}", c.ordinal)
            };
            let mut text = if same {
                last.as_ref().unwrap()["text"]
                    .as_str()
                    .unwrap_or("")
                    .to_owned()
            } else {
                String::new()
            };
            let chunk = u["content"]["text"].as_str();
            let mut truncated = false;
            if let Some(t) = chunk {
                if text.len() + t.len() <= s.limit / 2 {
                    text.push_str(t);
                } else {
                    truncated = true;
                    c.loss("record_size_limit");
                }
            }
            let mut content = if chunk.is_some() {
                vec![if kind == "agent_thought_chunk" {
                    common::reasoning(Some(&text), None)
                } else {
                    common::text(&text)
                }]
            } else {
                parts(&json!([u["content"]]), c)
            };
            if kind == "agent_thought_chunk" && chunk.is_none() {
                content.clear();
                c.loss("reasoning");
            }
            let mut r = json!({"type":"message","role":if kind=="user_message_chunk" {"user"}else{"assistant"},"content":content});
            if kind != "user_message_chunk" {
                r["author"] = json!("model");
                if let Some(id) = s
                    .entity("grok-active")?
                    .and_then(|v| v.as_str().map(str::to_owned))
                {
                    r["inferenceId"] = json!(id);
                }
            }
            if truncated {
                r["truncated"] = json!(true);
            }
            c.emit(s, r, string(&u["messageId"]), Some(&key))?;
            s.save(
                "grok-chunks",
                &json!({"key":key,"boundary":boundary,"text":text,"ordinal":c.ordinal}),
            )?;
        }
        Some("tool_call" | "tool_call_update") => {
            let Some(id) = string(&u["toolCallId"]) else {
                return Ok(());
            };
            let key = format!("grok-tool:{id}");
            let count_key = format!("grok-starts:{id}");
            let mut starts = s.entity(&count_key)?.and_then(|v| v.as_u64()).unwrap_or(0);
            if u["sessionUpdate"] == "tool_call" {
                starts += 1;
                s.save(&count_key, &json!(starts))?;
            }
            let mut state = if starts > 1 {
                u.clone()
            } else {
                s.entity(&key)?.unwrap_or(json!({}))
            };
            for (k, val) in u.as_object().into_iter().flatten() {
                if val.is_null() {
                    state.as_object_mut().unwrap().remove(k);
                } else {
                    state[k] = val.clone();
                }
            }
            s.save(&key, &state)?;
            let mut r = json!({"type":"tool_call","callId":id});
            let tool = &state["_meta"]["x.ai/tool"];
            if let Some(n) = tool["name"].as_str().or_else(|| state["name"].as_str()) {
                r["name"] = json!(n);
            }
            copy(&mut r, "kind", &state, "kind");
            copy(&mut r, "input", &state, "rawInput");
            if let Some(locs) = state["locations"].as_array() {
                r["locations"] = json!(locs
                    .iter()
                    .filter_map(|l| {
                        let mut r =
                            json!({"path":common::path(l["path"].as_str()?,c.cwd.as_deref())});
                        if let Some(n) = count(&l["line"]).filter(|n| *n > 0) {
                            r["line"] = json!(n);
                        }
                        Some(r)
                    })
                    .collect::<Vec<_>>());
            }
            if let Some(inf) = s
                .entity("grok-active")?
                .and_then(|v| v.as_str().map(str::to_owned))
            {
                r["inferenceId"] = json!(inf);
            }
            if u["sessionUpdate"] == "tool_call" && starts > 1 {
                c.emit(s, r, None, None)?;
                c.loss("ambiguous_tool_updates");
            } else if starts <= 1
                && (u["sessionUpdate"] == "tool_call"
                    || u.get("rawInput").is_some()
                    || u.get("kind").is_some()
                    || u.get("locations").is_some()
                    || u.get("name").is_some())
            {
                c.emit(s, r, None, Some(&format!("grok-call:{id}")))?;
            }
            if matches!(
                state["status"].as_str(),
                Some("completed" | "failed" | "cancelled")
            ) {
                let mut r = json!({"type":"tool_result","callId":id,"status":state["status"]});
                meta(c, &mut r, "displayContent", &state["content"]);
                meta(c, &mut r, "rawOutput", &state["rawOutput"]);
                if let Some(code) = state["rawOutput"]["exit_code"].as_i64() {
                    r["exec"]["exitCode"] = json!(code);
                }
                c.result(s, r)?;
            }
        }
        Some("turn_completed") => {
            s.save("grok-active", &Value::Null)?;
        }
        Some("current_mode_update") => {
            if let Some(mode) = u.get("currentModeId") {
                c.settings(s, json!({"mode":mode}))?;
            }
        }
        Some("session_info_update") => {
            if let Some(t) = u["title"].as_str() {
                c.info(s, json!({"type":"session_info","title":t}))?;
            }
        }
        _ => {}
    }
    Ok(())
}
