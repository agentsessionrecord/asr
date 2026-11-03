//! Claude transcript mapping with disk-backed folding by provider response identity.
use crate::{
    common::{self, copy, parts, Context},
    spool::Spool,
    Agent, Result,
};
use serde_json::{json, Value};

pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if let Some(cwd) = v["cwd"]
        .as_str()
        .filter(|p| common::absolute(p))
        .filter(|_| c.cwd.is_none())
    {
        c.cwd = Some(cwd.into());
    }
    if let Some(policy) = v.get("permissionMode") {
        if s.entity("permission-mode")?.as_ref() != Some(policy) {
            let mut settings = json!({"approval":policy});
            if matches!(policy.as_str(), Some("default" | "acceptEdits" | "plan")) {
                settings["asks"] = json!("sometimes");
            }
            c.settings(s, settings)?;
            s.save("permission-mode", policy)?;
        }
    }
    match v["type"].as_str().unwrap_or_default() {
        "assistant" => assistant(s, c, v),
        "user" => user(s, c, v),
        "attachment" => attachment(s, c, v),
        "api-request-shape" => {
            if let Some(tools) = v["shape"]["tools"].as_array() {
                let tools: Vec<_> = tools
                    .iter()
                    .filter_map(|tool| {
                        let mut r = json!({"name":tool["name"].as_str()?});
                        copy(&mut r, "description", tool, "description");
                        copy(&mut r, "inputSchema", tool, "input_schema");
                        Some(r)
                    })
                    .collect();
                c.info(s, json!({"type":"session_info","tools":tools}))?;
            }
            if let Some(system) = v["shape"].get("system") {
                c.emit(s,json!({"type":"message","role":"system","author":"harness","origin":"instructions","content":parts(system,Agent::ClaudeCode)}),None,None)?;
            }
            c.vendor(s, v)
        }
        "api-request" => {
            if let Some(id) = v["id"].as_str() {
                s.save(&format!("request:{id}"), v)?;
            }
            c.vendor(s, v)
        }
        "cost-state" => {
            if let Some(amount) = v
                .get("totalCostUSD")
                .or_else(|| v.get("costUSD"))
                .filter(|v| v.is_number())
            {
                c.info(s,json!({"type":"session_info","cost":{"amount":amount,"currency":"USD","source":"harness_estimated"}}))
            } else {
                c.vendor(s, v)
            }
        }
        "custom-title" | "ai-title" => {
            if let Some(title) = v
                .get("customTitle")
                .or_else(|| v.get("aiTitle"))
                .or_else(|| v.get("title"))
                .filter(|v| v.is_string())
            {
                c.info(s, json!({"type":"session_info","title":title}))
            } else {
                c.vendor(s, v)
            }
        }
        "mode" | "permission-mode" => {
            let mut settings = json!({});
            copy(&mut settings, "mode", v, "mode");
            copy(&mut settings, "approval", v, "permissionMode");
            c.settings(s, settings)
        }
        "system" if v["subtype"] == "compact_boundary" => {
            c.vendor(s, v)?;
            if v.pointer("/compactMetadata/preTokens").is_some() {
                c.loss("compaction_history");
            }
            Ok(())
        }
        "_gap" => c.emit(s, v["record"].clone(), None, None),
        _ => c.vendor(s, v),
    }
}
fn assistant(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    let message = &v["message"];
    if message["model"] == "<synthetic>" {
        return c.emit(s,json!({"type":"message","role":"assistant","author":"harness","status":if v["isApiErrorMessage"]==true {"error"} else {"complete"},"content":parts(&message["content"],c.agent)}),v["uuid"].as_str(),None);
    }
    let Some(response) = message["id"].as_str() else {
        if message.get("content").is_some() {
            return c.emit(s,json!({"type":"message","role":"assistant","author":"model","content":parts(&message["content"],c.agent)}),v["uuid"].as_str(),None);
        }
        return c.vendor(s, v);
    };
    // A response can have separate text blocks interleaved with tool outcomes.
    // Each block belongs at its completion point. The inference ends at its last observation.
    let content = parts(&message["content"], c.agent);
    if !content.is_empty() {
        let key = format!("message:{response}");
        let mut r = json!({"type":"message","role":"assistant","author":"model","inferenceId":response,"content":content});
        if let Some(old) = s.entity(&key)? {
            let mut assembled = old["content"].as_array().cloned().unwrap_or_default();
            assembled.extend(r["content"].as_array().into_iter().flatten().cloned());
            if serde_json::to_vec(&assembled)?.len() <= s.limit / 2 {
                r["content"] = json!(assembled);
            } else {
                r["truncated"] = json!(true);
                c.loss("record_size_limit");
            }
        }
        if v["isApiErrorMessage"] == true {
            r["status"] = json!("error");
        }
        if let Some(copy) = copied(v, c.agent) {
            r["copiedFrom"] = copy;
        }
        s.save(&key, &r)?;
        c.emit(s, r, None, Some(&key))?;
    }
    for block in message["content"].as_array().into_iter().flatten() {
        if block["type"] != "tool_use" {
            continue;
        }
        let id = block["id"].as_str().map(str::to_owned).unwrap_or_else(|| {
            asr_core::identity::derive_id(&[response, &c.pos.to_string(), &c.slot.to_string()])
        });
        let mut native = v.clone();
        native["id"] = json!(id);
        let input = block.get("input").map(|v| ("input", v.clone()));
        common::call(s, c, &native, &id, block["name"].as_str(), input)?;
    }
    let mut inference = json!({"type":"inference"});
    if let Some(model) = message["model"]
        .as_str()
        .filter(|s| !s.is_empty() && *s != "<synthetic>")
    {
        inference["model"] = json!({"id":model});
    } else {
        c.loss("model");
    }
    copy(&mut inference, "stopReason", message, "stop_reason");
    if inference["stopReason"].is_null() {
        inference.as_object_mut().unwrap().remove("stopReason");
    }
    let usage = &message["usage"];
    if usage.is_object() {
        let placeholder = message["model"] == "<synthetic>"
            || (message["stop_reason"].is_null()
                && [
                    "input_tokens",
                    "output_tokens",
                    "cache_read_input_tokens",
                    "cache_creation_input_tokens",
                ]
                .iter()
                .all(|key| usage[*key].as_u64().unwrap_or(0) == 0));
        if !placeholder {
            inference["usage"] = tokens(usage);
        }
    }
    let request = v["requestRef"]
        .as_str()
        .map(|id| s.entity(&format!("request:{id}")))
        .transpose()?
        .flatten();
    let mut settings = json!({});
    if let Some(request) = request {
        let p = &request["params"];
        for (dest, pointer) in [
            ("maxOutputTokens", "/max_tokens"),
            ("serviceTier", "/service_tier"),
            ("reasoningEffort", "/output_config/effort"),
        ] {
            if let Some(value) = p.pointer(pointer) {
                settings[dest] = value.clone();
            }
        }
    }
    if let Some(tier) = usage.get("service_tier") {
        inference["_meta"][c.agent.domain()]["servedServiceTier"] = tier.clone();
    }
    if settings.as_object().is_some_and(|o| !o.is_empty()) {
        inference["settings"] = settings;
    }
    if let Some(copy) = copied(v, c.agent) {
        inference["copiedFrom"] = copy;
    }
    c.emit(
        s,
        inference,
        Some(response),
        Some(&format!("inference:{response}")),
    )
}
fn tokens(usage: &Value) -> Value {
    let mut out = json!({});
    if let Some(base) = usage["input_tokens"].as_u64() {
        if let Some(total) = base
            .checked_add(usage["cache_read_input_tokens"].as_u64().unwrap_or(0))
            .and_then(|n| n.checked_add(usage["cache_creation_input_tokens"].as_u64().unwrap_or(0)))
        {
            out["inputTokens"] = json!(total);
        }
    }
    for (dest, source) in [
        ("cacheReadTokens", "cache_read_input_tokens"),
        ("cacheWriteTokens", "cache_creation_input_tokens"),
        ("outputTokens", "output_tokens"),
    ] {
        if usage[source].is_u64() {
            copy(&mut out, dest, usage, source);
        }
    }
    out
}
fn copied(v: &Value, agent: Agent) -> Option<Value> {
    let session = v.pointer("/forkedFrom/sessionId")?.as_str()?;
    let mut copy = json!({"session":asr_core::identity::session_ref(agent.name(),None,session)});
    if let Some(record) = v.pointer("/forkedFrom/messageUuid").and_then(Value::as_str) {
        copy["record"] = json!(record);
    }
    Some(copy)
}
fn user(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    let content = &v["message"]["content"];
    let body = parts(content, c.agent);
    if !body.is_empty() || content.as_array().is_some_and(|a| a.is_empty()) {
        let mut r = json!({"type":"message","role":"user","content":body});
        if v["isCompactSummary"] == true {
            r["origin"] = json!("compaction");
            r["author"] = json!("harness");
        } else {
            prompt_origin(v, &mut r, c.agent);
        }
        if let Some(copy) = copied(v, c.agent) {
            r["copiedFrom"] = copy;
        }
        c.emit(s, r, v["uuid"].as_str(), None)?;
        if v["isCompactSummary"] == true {
            c.emit(s,json!({"type":"gap","reason":"not_retained","detail":"Native compaction discarded earlier history."}),None,None)?;
        }
    }
    for block in content.as_array().into_iter().flatten() {
        if block["type"] != "tool_result" {
            continue;
        }
        let call = block["tool_use_id"].as_str();
        let output = &v["toolUseResult"];
        let status = match block["is_error"].as_bool() {
            Some(true) => "failed",
            Some(false) => "completed",
            None if output.is_object() => "completed",
            None => "unknown",
        };
        if let Some(call) = call {
            approval(s, c, call, v.get("permissionDecision"))?;
        }
        let mut r = json!({"type":"tool_result","status":status});
        if let Some(call) = call {
            r["callId"] = json!(call);
        }
        if let Some(content) = block.get("content") {
            r["content"] = json!(parts(content, c.agent));
        }
        if let Some(effective) = v.get("updatedInput").or_else(|| output.get("updatedInput")) {
            r["input"] = effective.clone();
        }
        let mut exec = json!({});
        for (dest, key) in [
            ("stdout", "stdout"),
            ("stderr", "stderr"),
            ("exitCode", "exitCode"),
            ("signal", "signal"),
        ] {
            copy(&mut exec, dest, output, key);
        }
        if let Some(call) = call {
            if let Some(native) = s.entity(&format!("call:{call}"))? {
                if native["name"] == "Bash" {
                    copy(&mut exec, "command", &native["input"], "command");
                }
            }
        }
        if exec.as_object().is_some_and(|o| !o.is_empty()) {
            r["exec"] = exec;
        }
        let status = if output["interrupted"] == true {
            "interrupted"
        } else {
            status
        };
        r["status"] = json!(status);
        c.result(s, r)?;
        if let Some(call) = call {
            file_change(s, c, call, output, v.get("updatedInput"), status)?;
        }
    }
    Ok(())
}
fn prompt_origin(v: &Value, r: &mut Value, agent: Agent) {
    let kind = v["origin"]["kind"].as_str();
    if v["isMeta"] == true {
        r["author"] = json!("harness");
        r["origin"] = json!("injected");
    } else if kind == Some("human") {
        r["author"] = json!("human");
        r["origin"] = json!(
            if v["origin"]["queued"] == true || v["turnOrigin"] == "queued" {
                "queued"
            } else {
                "prompt"
            }
        );
    } else if matches!(kind, Some("peer" | "coordinator" | "observer")) {
        r["author"] = json!("agent");
        r["origin"] = json!("subagent_report");
        if let Some(from) = v["origin"]["fromSession"]
            .as_str()
            .or_else(|| v["fromSession"].as_str())
        {
            r["from"] = json!(asr_core::identity::session_ref(agent.name(), None, from));
        }
    } else if kind == Some("scheduled") {
        r["origin"] = json!("scheduled");
    } else if kind == Some("channel") {
        r["origin"] = json!("external");
    }
    for key in [
        "origin",
        "turnOrigin",
        "promptSource",
        "userType",
        "scheduledTaskId",
        "scheduledFireId",
        "fireReason",
    ] {
        if let Some(value) = v.get(key) {
            r["_meta"][agent.domain()][key] = value.clone();
        }
    }
}
fn approval(s: &Spool, c: &mut Context, call: &str, native: Option<&Value>) -> Result<()> {
    let Some(native) = native else {
        return Ok(());
    };
    let decision = match native["decision"].as_str() {
        Some("accept" | "allow") => "approved",
        Some("reject" | "deny") => "denied",
        Some("abort" | "cancelled") => "cancelled",
        _ => return Ok(()),
    };
    let mut r = json!({"type":"approval","callId":call,"decision":decision,"native":native});
    if decision != "cancelled" {
        let by = match (native["reasonType"].as_str(), native["source"].as_str()) {
            (Some("mode"), _) => Some("mode"),
            (Some("classifier"), _) => Some("classifier"),
            (_, Some("hook")) => Some("hook"),
            (_, Some("config")) => Some("policy"),
            (_, Some("user_reject" | "user")) => Some("user"),
            _ => None,
        };
        if let Some(by) = by {
            r["by"] = json!(by);
        }
        if native["source"] == "user_permanent" {
            r["scope"] = json!("always");
        }
    }
    // A result snapshot has no independent decision position or timestamp.
    let timestamp = c.source.as_object_mut().unwrap().remove("ts");
    c.emit(s, r, None, Some(&format!("approval:{call}:{}", native)))?;
    if let Some(ts) = timestamp {
        c.source["ts"] = ts;
    }
    Ok(())
}
fn file_change(
    s: &Spool,
    c: &mut Context,
    call: &str,
    output: &Value,
    effective: Option<&Value>,
    status: &str,
) -> Result<()> {
    let native = s.entity(&format!("call:{call}"))?.unwrap_or(Value::Null);
    let input = effective
        .or_else(|| output.get("updatedInput"))
        .unwrap_or(&native["input"]);
    let name = native["name"].as_str();
    let Some(file) = output["filePath"]
        .as_str()
        .or_else(|| input["file_path"].as_str())
    else {
        return Ok(());
    };
    let op = match output["type"].as_str() {
        Some("create") => "add",
        Some("update" | "edit") => "modify",
        Some("delete") => "delete",
        _ if matches!(name, Some("Edit" | "MultiEdit")) => "modify",
        _ => "unknown",
    };
    if !output.is_object() && !matches!(name, Some("Edit" | "MultiEdit" | "Write" | "NotebookEdit"))
    {
        return Ok(());
    }
    let applied = status == "completed" && output["staged"] != true;
    let mut r = json!({"type":"file_change","callId":call,"path":common::path(file,c.cwd.as_deref()),"op":op,"status":match status {"completed" if output["staged"]==true => "proposed", "completed"=>"applied", "failed"=>"failed", _=>"unknown"}});
    if let Some(text) = output["originalFile"].as_str() {
        r["before"] = json!({"text":text});
    }
    if matches!(name, Some("Write")) || matches!(output["type"].as_str(), Some("create" | "update"))
    {
        if let Some(text) = output["content"]
            .as_str()
            .or_else(|| applied.then(|| input["content"].as_str()).flatten())
        {
            r["after"] = json!({"text":text});
        }
    }
    let edit = |v: &Value| {
        Some(
            json!({"oldText":v["oldString"].as_str().or_else(||v["old_string"].as_str())?,"newText":v["newString"].as_str().or_else(||v["new_string"].as_str())?}),
        )
    };
    let edits = output
        .get("edits")
        .or_else(|| applied.then(|| input.get("edits")).flatten());
    if let Some(edits) = edits.and_then(Value::as_array) {
        let normalized: Vec<_> = edits.iter().filter_map(edit).collect();
        if normalized.len() != edits.len() {
            c.loss("file_changes");
        }
        r["edits"] = json!(normalized);
    } else if let Some(edit) = edit(output).or_else(|| applied.then(|| edit(input)).flatten()) {
        r["edits"] = json!([edit]);
    }
    r["_meta"] = json!({c.agent.domain():{"result":output}});
    c.emit(s, r, None, None)
}
fn attachment(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    let attachment = &v["attachment"];
    if attachment["type"] == "prompt_snapshot" {
        if let Some(prompts) = attachment["systemPrompt"].as_array() {
            let content: Vec<_> = prompts
                .iter()
                .filter_map(Value::as_str)
                .map(common::text)
                .collect();
            if !content.is_empty() {
                c.emit(s,json!({"type":"message","role":"system","origin":"instructions","author":"harness","content":content}),v["uuid"].as_str(),None)?;
            }
        }
    } else if let Some(rendered) = v["rendered"].as_array() {
        let content: Vec<_> = rendered
            .iter()
            .filter_map(|p| p["content"].as_str())
            .map(common::text)
            .collect();
        if !content.is_empty() {
            c.emit(s,json!({"type":"message","role":v["renderedRole"].as_str().unwrap_or("user"),"author":"harness","origin":"injected","content":content}),v["uuid"].as_str(),None)?;
        }
    }
    c.vendor(s, v)
}
