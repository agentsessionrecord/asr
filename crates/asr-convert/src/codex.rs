//! Codex rollout mapping. Usage records establish inference boundaries.
use crate::{
    common::{self, copy, parts, Context},
    spool::Spool,
    Agent, Result,
};
use serde_json::{json, Value};

pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    let p = &v["payload"];
    match v["type"].as_str().unwrap_or_default() {
        "session_meta" => {
            if let Some(cwd) = p["cwd"].as_str().filter(|p| common::absolute(p)) {
                c.cwd = Some(cwd.into());
            }
            if let Some(provider) = p["model_provider"].as_str() {
                s.save("provider", &json!(provider))?;
            }
            instructions(s, c, p)?;
            c.vendor(s, v)
        }
        "turn_context" => {
            if let Some(turn) = p["turn_id"].as_str().or(c.turn.as_deref()) {
                s.save(&format!("turn:{turn}"), p)?;
            }
            c.settings = p.clone();
            instructions(s, c, p)?;
            settings(s, c, p)
        }
        "response_item" => response(s, c, p, v),
        "token_usage_record" => inference(s, c, p),
        "compacted" => compaction(s, c, p),
        "event_msg" => event(s, c, p, v),
        "world_state" => {
            c.vendor(s, v)?;
            if p["full"] == true {
                for key in [
                    "agents_md",
                    "host_skills",
                    "permissions",
                    "managed_developer_instructions",
                ] {
                    if let Some(text) = p["state"][key]
                        .as_str()
                        .or_else(|| p["state"][key]["text"].as_str())
                        .or_else(|| p["state"][key]["body"].as_str())
                    {
                        c.emit(s,json!({"type":"message","role":"developer","author":"harness","origin":"instructions","content":[common::text(text)]}),None,None)?;
                    }
                }
            }
            Ok(())
        }
        "_gap" => c.emit(s, v["record"].clone(), None, None),
        _ => c.vendor(s, v),
    }
}
fn instructions(s: &Spool, c: &mut Context, p: &Value) -> Result<()> {
    for (field, role) in [
        ("base_instructions", "system"),
        ("developer_instructions", "developer"),
    ] {
        if let Some(text) = p[field].as_str().or_else(|| p[field]["text"].as_str()) {
            c.emit(s,json!({"type":"message","role":role,"origin":"instructions","author":"harness","content":[common::text(text)]}),None,None)?;
        }
    }
    if let Some(definitions) = p["additional_tools"].as_array() {
        let tools: Vec<_> = definitions
            .iter()
            .filter_map(|tool| {
                let mut r = json!({"name":tool["name"].as_str()?});
                copy(&mut r, "description", tool, "description");
                copy(&mut r, "inputSchema", tool, "input_schema");
                copy(&mut r, "source", tool, "namespace");
                Some(r)
            })
            .collect();
        c.loss("tools");
        c.info(s, json!({"type":"session_info","tools":tools}))?;
    }
    Ok(())
}
fn settings(s: &Spool, c: &mut Context, p: &Value) -> Result<()> {
    let mut settings = json!({});
    for (dest, key) in [
        ("approval", "approval_policy"),
        ("sandbox", "sandbox_policy"),
    ] {
        if let Some(v) = p.get(key) {
            settings[dest] = v.clone();
        }
    }
    if let Some(mode) = p.pointer("/collaboration_mode/mode") {
        settings["mode"] = mode.clone();
    }
    for (dest, key) in [
        ("reasoningEffort", "reasoning_effort"),
        ("serviceTier", "service_tier"),
    ] {
        if let Some(v) = p.get(key) {
            settings["modelSettings"][dest] = v.clone();
        }
    }
    if p["approvals_reviewer"].as_str().is_none_or(|v| v == "user") {
        match settings["approval"].as_str() {
            Some("never") => settings["asks"] = json!("never"),
            Some("on-request" | "untrusted") => settings["asks"] = json!("sometimes"),
            _ => {}
        }
    }
    if settings["sandbox"]["type"] == "external-sandbox"
        || settings["sandbox"] == "external-sandbox"
    {
        settings["externalSandbox"] = json!({"source":"setting","native":settings["sandbox"]});
    }
    c.settings(s, settings)
}
fn response(s: &Spool, c: &mut Context, p: &Value, v: &Value) -> Result<()> {
    match p["type"].as_str().unwrap_or_default() {
        "message" | "reasoning" => {
            if p["status"] == "in_progress" {
                c.loss("streaming_updates");
                return c.vendor(s, v);
            }
            let mut r = json!({"type":"message","role":p["role"].as_str().unwrap_or("assistant"),"content":parts(&p["content"],c.agent)});
            if p["type"] == "reasoning" {
                r["role"] = json!("assistant");
                let summary: Vec<_> = p["summary"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter_map(|v| v["text"].as_str())
                    .collect();
                let mut reasoning = json!({"type":"reasoning"});
                if p["encrypted_content"].is_string() {
                    reasoning["visibility"] = json!("encrypted");
                    c.loss("reasoning");
                } else if p["summary"].is_array() {
                    reasoning["summary"] = json!(summary);
                    reasoning["visibility"] = json!("summary");
                }
                r["content"] = json!([reasoning]);
            }
            if r["role"] == "assistant" {
                r["author"] = json!("model");
            }
            if r["role"] == "system" || r["role"] == "developer" {
                r["origin"] = json!("instructions");
            }
            if let Some(kinds) = p
                .pointer("/internal_chat_message_metadata_passthrough/content_item_kinds")
                .and_then(Value::as_array)
            {
                for (index, part) in r["content"]
                    .as_array_mut()
                    .into_iter()
                    .flatten()
                    .enumerate()
                {
                    match kinds.get(index).and_then(Value::as_str) {
                        Some("user.text" | "user.image") => {
                            part["author"] = json!("human");
                            part["origin"] = json!("prompt");
                        }
                        Some(
                            "environments.environment_context"
                            | "harness.environment_context"
                            | "environment_context",
                        ) => {
                            part["author"] = json!("harness");
                            part["origin"] = json!("injected");
                        }
                        Some(
                            "agents_md.instructions"
                            | "permissions.instructions"
                            | "collaboration_mode.instructions"
                            | "host_skills.instructions",
                        ) => {
                            part["author"] = json!("harness");
                            part["origin"] = json!("instructions");
                        }
                        Some("hooks.additional_context") => {
                            part["author"] = json!("hook");
                            part["origin"] = json!("injected");
                        }
                        Some("multi_agent.subagent_notification") => {
                            part["author"] = json!("agent");
                            part["origin"] = json!("subagent_report");
                        }
                        _ => {}
                    }
                }
            }
            if let Some(phase) = p["phase"].as_str() {
                r["phase"] = json!(if phase == "final_answer" {
                    "final"
                } else {
                    phase
                });
            }
            if let Some(response) = p["response_id"]
                .as_str()
                .or_else(|| v["response_id"].as_str())
            {
                r["inferenceId"] = json!(response);
            }
            if let Some(status) = p["status"].as_str() {
                r["status"] = json!(match status {
                    "completed" => "complete",
                    "incomplete" => "interrupted",
                    v => v,
                });
            }
            if let Some(copy) = p
                .pointer("/retained_source/session_id")
                .and_then(Value::as_str)
                .filter(|id| *id != c.session)
            {
                r["copiedFrom"] =
                    json!({"session":asr_core::identity::session_ref(c.agent.name(),None,copy)});
            }
            let id = p["id"].as_str();
            let fold = id.map(|id| format!("message:{id}"));
            c.emit(s, r, id, fold.as_deref())
        }
        "function_call" | "custom_tool_call" | "local_shell_call" | "tool_search_call" => {
            let derived = asr_core::identity::derive_id(&[&c.session, &c.pos.to_string(), "call"]);
            let id = p["call_id"]
                .as_str()
                .or_else(|| p["id"].as_str())
                .unwrap_or(&derived);
            let input = p
                .get("arguments")
                .or_else(|| p.get("input"))
                .or_else(|| p.get("action"))
                .map(|raw| {
                    if let Some(text) = raw.as_str() {
                        if p["type"] == "function_call" {
                            if let Ok(mut parsed) = asr_core::jsonl::decode(text) {
                                asr_core::jsonl::stringify_large_native(&mut parsed);
                                return ("input", parsed);
                            }
                        }
                        ("inputText", json!(text))
                    } else {
                        ("input", raw.clone())
                    }
                });
            common::call(s, c, p, id, p["name"].as_str(), input)
        }
        "function_call_output" | "custom_tool_call_output" | "tool_search_output" => {
            let mut r = json!({"type":"tool_result","status":"unknown"});
            copy(&mut r, "callId", p, "call_id");
            if let Some(output) = p.get("output") {
                r["content"] = json!(parts(output, c.agent));
            }
            c.result(s, r)
        }
        "compaction" | "compaction_summary" | "context_compaction" => compaction(s, c, p),
        _ => c.vendor(s, v),
    }
}
fn tokens(p: &Value) -> Value {
    let mut out = json!({});
    for (dest, key) in [
        ("inputTokens", "input_tokens"),
        ("cacheReadTokens", "cached_input_tokens"),
        ("cacheWriteTokens", "cache_write_input_tokens"),
        ("outputTokens", "output_tokens"),
        ("reasoningTokens", "reasoning_output_tokens"),
    ] {
        if p[key].is_u64() {
            copy(&mut out, dest, p, key);
        }
    }
    out
}
fn inference(s: &Spool, c: &mut Context, p: &Value) -> Result<()> {
    let Some(id) = p["response_id"].as_str() else {
        c.loss("usage");
        return Ok(());
    };
    let mut r = json!({"type":"inference"});
    if p["usage"].is_object() {
        r["usage"] = tokens(&p["usage"]);
    }
    let turn = p["turn_id"].as_str().or(c.turn.as_deref());
    let context = turn
        .map(|turn| s.entity(&format!("turn:{turn}")))
        .transpose()?
        .flatten();
    if let Some(context) = context {
        if let Some(model) = context["model"].as_str() {
            r["model"] = json!({"requested":model});
        }
        let mut settings = json!({});
        copy(&mut settings, "reasoningEffort", &context, "effort");
        copy(&mut settings, "serviceTier", &context, "service_tier");
        if settings.as_object().is_some_and(|o| !o.is_empty()) {
            r["settings"] = settings;
        }
    }
    if let Some(model) = p["model"].as_str() {
        r["model"]["id"] = json!(model);
    }
    if r["model"].is_object() {
        if let Some(provider) = s.entity("provider")? {
            r["model"]["provider"] = provider;
        }
    } else {
        r.as_object_mut().unwrap().remove("model");
        c.loss("model");
    }
    c.emit(s, r, Some(id), Some(&format!("inference:{id}")))?;
    if p["thread_token_usage"].is_object() {
        c.info(
            s,
            json!({"type":"session_info","usage":tokens(&p["thread_token_usage"])}),
        )?;
    }
    Ok(())
}
fn event(s: &Spool, c: &mut Context, p: &Value, v: &Value) -> Result<()> {
    match p["type"].as_str().unwrap_or_default() {
        "thread_settings_applied" => settings(s, c, &p["thread_settings"]),
        "token_count" => {
            if p.pointer("/info/total_token_usage")
                .is_some_and(Value::is_object)
            {
                c.info(
                    s,
                    json!({"type":"session_info","usage":tokens(&p["info"]["total_token_usage"])}),
                )?;
            }
            Ok(())
        }
        "exec_command_end" | "patch_apply_end" => execution(s, c, p),
        "item_completed" => match p["item"]["type"].as_str() {
            Some("FileChange" | "CommandExecution") => item(s, c, &p["item"]),
            _ => c.vendor(s, v),
        },
        "approval_response" | "exec_approval_response" | "patch_approval_response" => {
            approval(s, c, p)
        }
        _ => c.vendor(s, v),
    }
}
fn execution(s: &Spool, c: &mut Context, p: &Value) -> Result<()> {
    let mut r = json!({"type":"tool_result","status":status(p)});
    copy(&mut r, "callId", p, "call_id");
    let mut exec = json!({});
    for (dest, key) in [
        ("stdout", "stdout"),
        ("stderr", "stderr"),
        ("output", "aggregated_output"),
        ("exitCode", "exit_code"),
        ("command", "command"),
    ] {
        copy(&mut exec, dest, p, key);
    }
    if exec.as_object().is_some_and(|o| !o.is_empty()) {
        r["exec"] = exec;
    }
    c.result(s, r)?;
    if p["type"] == "patch_apply_end" {
        if let Some(id) = p["call_id"].as_str() {
            if p["changes"].is_object() {
                file_changes(s, c, id, &p["changes"], status(p))?;
            } else if let Some(call) = s.entity(&format!("call:{id}"))? {
                if call["name"] == "apply_patch" {
                    if let Some(patch) = call["inputText"].as_str() {
                        patch_changes(s, c, id, patch, status(p))?;
                    }
                }
            }
        }
    }
    Ok(())
}
fn status(p: &Value) -> &'static str {
    match p["status"].as_str() {
        Some("completed" | "succeeded" | "success") => "completed",
        Some("failed") => "failed",
        Some("declined" | "denied") => "denied",
        Some("cancelled") => "cancelled",
        Some("interrupted") => "interrupted",
        _ => match p["success"].as_bool() {
            Some(true) => "completed",
            Some(false) => "failed",
            None => "unknown",
        },
    }
}
fn item(s: &Spool, c: &mut Context, item: &Value) -> Result<()> {
    let Some(id) = item["id"].as_str() else {
        return c.vendor(s, item);
    };
    // The invocation ID is source evidence of a distinct execution, even if its name is absent.
    let mut call = json!({"type":"tool_call","callId":id,"kind":if item["type"]=="FileChange" {"edit"} else {"execute"}});
    copy(&mut call, "name", item, "name");
    c.emit(s, call, Some(id), Some(&format!("invocation:{id}")))?;
    let status = status(item);
    let mut result = json!({"type":"tool_result","callId":id,"status":status});
    if item["type"] == "CommandExecution" {
        let mut exec = json!({});
        for (dest, key) in [
            ("command", "command"),
            ("exitCode", "exit_code"),
            ("output", "aggregated_output"),
        ] {
            copy(&mut exec, dest, item, key);
        }
        result["exec"] = exec;
    }
    c.result(s, result)?;
    file_changes(s, c, id, &item["changes"], status)
}
fn file_changes(s: &Spool, c: &mut Context, id: &str, changes: &Value, status: &str) -> Result<()> {
    for (file, change) in changes.as_object().into_iter().flatten() {
        let op = match change["type"].as_str() {
            Some("add") => "add",
            Some("delete") => "delete",
            Some("update") => "modify",
            _ => "unknown",
        };
        let mut r = json!({"type":"file_change","callId":id,"path":common::path(file,c.cwd.as_deref()),"op":op,"status":if status=="completed" {"applied"} else if status=="failed" {"failed"} else {"unknown"}});
        if op == "add" {
            if let Some(content) = change["content"].as_str() {
                r["after"] = json!({"text":content});
            }
        }
        if let Some(diff) = change["unified_diff"].as_str() {
            r["patch"] = json!(diff);
        }
        if let Some(target) = change["move_path"].as_str() {
            r["oldPath"] = r["path"].clone();
            r["path"] = json!(common::path(target, c.cwd.as_deref()));
            r["op"] = json!("move");
        }
        c.emit(s, r, None, Some(&format!("change:{id}:{file}")))?;
    }
    Ok(())
}
fn patch_changes(s: &Spool, c: &mut Context, id: &str, patch: &str, status: &str) -> Result<()> {
    // Unsupported framing stays native evidence rather than becoming altered edit text.
    let Some(changes) = parsed_patch(patch) else {
        c.loss("file_changes");
        return Ok(());
    };
    for mut r in changes {
        let file = r["path"].as_str().unwrap().to_owned();
        r["type"] = json!("file_change");
        r["callId"] = json!(id);
        r["status"] = json!(match status {
            "completed" => "applied",
            "failed" => "failed",
            _ => "unknown",
        });
        r["path"] = json!(common::path(&file, c.cwd.as_deref()));
        if let Some(old) = r["oldPath"].as_str() {
            r["oldPath"] = json!(common::path(old, c.cwd.as_deref()));
        }
        c.emit(s, r, None, Some(&format!("change:{id}:{file}")))?;
    }
    Ok(())
}
fn parsed_patch(patch: &str) -> Option<Vec<Value>> {
    if patch.contains('\r') {
        return None;
    }
    let lines: Vec<_> = patch
        .strip_suffix('\n')
        .unwrap_or(patch)
        .split('\n')
        .collect();
    if lines.first() != Some(&"*** Begin Patch") || lines.last() != Some(&"*** End Patch") {
        return None;
    }
    let mut changes = Vec::new();
    let mut index = 1;
    while index + 1 < lines.len() {
        let (op, file) = if let Some(file) = lines[index].strip_prefix("*** Update File: ") {
            ("modify", file)
        } else if let Some(file) = lines[index].strip_prefix("*** Add File: ") {
            ("add", file)
        } else {
            ("delete", lines[index].strip_prefix("*** Delete File: ")?)
        };
        if file.is_empty() {
            return None;
        }
        let mut r = json!({"path":file,"op":op});
        let mut edits = Vec::new();
        let (mut old, mut new) = (String::new(), String::new());
        index += 1;
        if op == "modify" {
            if let Some(target) = lines
                .get(index)
                .and_then(|l| l.strip_prefix("*** Move to: "))
            {
                if target.is_empty() {
                    return None;
                }
                r["oldPath"] = r["path"].clone();
                r["path"] = json!(target);
                r["op"] = json!("move");
                index += 1;
            }
        }
        while index + 1 < lines.len() && !lines[index].starts_with("*** ") {
            let line = lines[index];
            if op == "delete" {
                return None;
            }
            if op == "modify" && (line == "@@" || line.starts_with("@@ ")) {
                if !old.is_empty() || !new.is_empty() {
                    edits.push(json!({"oldText":old,"newText":new}));
                    old.clear();
                    new.clear();
                }
            } else if let Some(t) = line.strip_prefix('+') {
                new.push_str(t);
                new.push('\n');
            } else if op == "modify" {
                if let Some(t) = line.strip_prefix('-') {
                    old.push_str(t);
                    old.push('\n');
                } else {
                    let t = line.strip_prefix(' ')?;
                    old.push_str(t);
                    old.push('\n');
                    new.push_str(t);
                    new.push('\n');
                }
            } else {
                return None;
            }
            index += 1;
        }
        if lines.get(index) == Some(&"*** End of File") && op == "modify" {
            index += 1;
        }
        if op == "add" {
            r["after"] = json!({"text":new});
        } else if op == "modify" {
            if !old.is_empty() || !new.is_empty() {
                edits.push(json!({"oldText":old,"newText":new}));
            }
            if !edits.is_empty() {
                r["edits"] = json!(edits);
            }
        }
        changes.push(r);
    }
    (!changes.is_empty()).then_some(changes)
}

fn approval(s: &Spool, c: &mut Context, p: &Value) -> Result<()> {
    let decision = match p["decision"].as_str() {
        Some("approved" | "accept" | "accept_for_session") => "approved",
        Some("denied" | "decline") => "denied",
        Some("cancelled" | "abort") => "cancelled",
        _ => return c.vendor(s, p),
    };
    let mut r = json!({"type":"approval","decision":decision,"native":p});
    copy(&mut r, "callId", p, "call_id");
    copy(&mut r, "subject", p, "subject");
    if p["reused"] == true {
        r["by"] = json!("policy");
    } else if decision != "cancelled" {
        copy(&mut r, "by", p, "by");
    }
    if decision == "approved" && p["decision"] == "accept_for_session" {
        r["scope"] = json!("session");
    }
    c.emit(s, r, p["id"].as_str(), None)
}
fn compaction(s: &Spool, c: &mut Context, p: &Value) -> Result<()> {
    let content = p
        .get("message")
        .or_else(|| p.get("summary"))
        .map(|p| parts(p, Agent::Codex))
        .unwrap_or_default();
    c.emit(s,json!({"type":"message","role":"user","author":"harness","origin":"compaction","content":content}),None,None)?;
    if p["replacement_history"]
        .as_array()
        .is_none_or(|a| a.is_empty())
    {
        c.emit(s,json!({"type":"gap","reason":"not_retained","detail":"Native compaction did not retain earlier context."}),None,None)?;
    }
    c.vendor(s, p)
}
