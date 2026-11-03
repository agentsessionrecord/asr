pub use crate::common::{count, nonempty as string, timestamp_millis as time};
use crate::{
    common::{self, Context},
    spool::Spool,
    Result,
};
use serde_json::{json, Value};
pub fn position(c: &mut Context, v: &Value) {
    c.source.as_object_mut().unwrap().remove("ts");
    let at = v
        .get("timestamp")
        .or_else(|| v.get("time"))
        .or_else(|| v.get("created_at"))
        .or_else(|| v.get("timestampMs"))
        .or_else(|| v.pointer("/params/_meta/agentTimestampMs"))
        .or_else(|| v.pointer("/_meta/agentTimestampMs"))
        .or_else(|| v.pointer("/params/_meta/timestamp"))
        .or_else(|| v.pointer("/_meta/timestamp"));
    let timestamp = if c.agent == crate::Agent::GrokBuild {
        v.pointer("/params/_meta/agentTimestampMs")
            .or_else(|| v.pointer("/_meta/agentTimestampMs"))
            .and_then(time)
            .or_else(|| {
                chrono::DateTime::from_timestamp(v["timestamp"].as_i64()?, 0)
                    .map(|t| t.to_rfc3339_opts(chrono::SecondsFormat::Secs, true))
            })
    } else {
        at.and_then(time)
    };
    if let Some(t) = timestamp {
        c.source["ts"] = json!(t);
    }
    // These families record their own turn identity. Do not borrow the previous turn.
    c.source.as_object_mut().unwrap().remove("turnId");
    let turn = v
        .pointer("/data/turnId")
        .or_else(|| v.pointer("/event/turnId"))
        .or_else(|| v.pointer("/goalContext/turnId"))
        .or_else(|| v.pointer("/params/_meta/promptId"))
        .or_else(|| v.pointer("/_meta/promptId"))
        .or_else(|| v.pointer("/data/turn"));
    if let Some(t) = turn {
        if let Some(t) = t
            .as_str()
            .map(str::to_owned)
            .or_else(|| t.as_i64().map(|n| n.to_string()))
        {
            c.source["turnId"] = json!(t);
        }
    }
    if let Some(cwd) = v["cwd"].as_str().filter(|p| common::absolute(p)) {
        if c.cwd.is_none() {
            c.cwd = Some(cwd.into());
        }
    }
}
pub fn native_id(v: &Value) -> Option<&str> {
    string(&v["uuid"]).or_else(|| string(&v["id"]))
}
pub fn parts(v: &Value, c: &Context) -> Vec<Value> {
    if let Some(t) = v.as_str() {
        return vec![common::text(t)];
    }
    let mut out = Vec::new();
    for p in v.as_array().into_iter().flatten() {
        if matches!(
            p["type"].as_str(),
            Some("toolCall" | "tool-call" | "tool-result" | "tool_use" | "tool_result")
        ) || p.get("functionCall").is_some()
            || p.get("functionResponse").is_some()
        {
            continue;
        }
        if p["type"] == "thinking" && p["redacted"] == true {
            out.push(json!({"type":"reasoning","visibility":"encrypted"}));
            continue;
        }
        if let Some(t) = p["text"].as_str().filter(|_| p.get("type").is_none()) {
            out.push(if p["thought"] == true {
                common::reasoning(Some(t), Some("summary"))
            } else {
                common::text(t)
            });
        } else if p["type"] == "think" {
            if let Some(t) = p["think"].as_str() {
                out.push(common::reasoning(Some(t), None));
            }
        } else {
            out.extend(common::parts(&json!([p]), c.agent));
        }
    }
    out
}
pub fn meta(c: &Context, r: &mut Value, key: &str, v: &Value) {
    r["_meta"][c.agent.domain()][key] = v.clone();
}
pub fn input(r: &mut Value, v: Option<&Value>) {
    if let Some(v) = v {
        if let Some(t) = v.as_str() {
            if let Ok(mut parsed) = asr_core::jsonl::decode(t) {
                asr_core::jsonl::stringify_large_native(&mut parsed);
                r["input"] = parsed;
            } else {
                r["inputText"] = v.clone();
            }
        } else {
            r["input"] = v.clone();
        }
    }
}
#[allow(clippy::too_many_arguments)]
pub fn call(
    s: &Spool,
    c: &mut Context,
    id: Option<&str>,
    name: Option<&str>,
    args: Option<&Value>,
    model: bool,
    native: Option<&str>,
    fold: Option<&str>,
    inf: Option<&str>,
) -> Result<()> {
    let id = id.map(str::to_owned).unwrap_or_else(|| {
        asr_core::identity::derive_id(&[
            &c.session,
            "call",
            &c.ordinal.to_string(),
            &c.slot.to_string(),
        ])
    });
    let mut r = json!({"type":"tool_call","callId":id});
    if let Some(n) = name {
        r["name"] = json!(n);
        if let Some(k) = kind(n) {
            r["kind"] = json!(k);
        }
    }
    if model {
        r["requestedBy"] = json!("model");
    }
    if let Some(i) = inf {
        r["inferenceId"] = json!(i);
    }
    input(&mut r, args);
    if let Some(p) = r["input"]["path"]
        .as_str()
        .or_else(|| r["input"]["file_path"].as_str())
    {
        r["locations"] = json!([{"path":common::path(p,c.cwd.as_deref())}]);
    }
    s.save(&format!("call:{id}"), &r)?;
    c.emit(s, r, native, fold)
}
pub fn kind(name: &str) -> Option<&'static str> {
    common::kind(name).or(match name {
        "read" | "ReadFile" | "view" => Some("read"),
        "write" | "edit" | "create" | "Create" | "ApplyPatch" | "str_replace" => Some("edit"),
        "Execute" | "run_shell_command" | "bash" | "bashExecution" => Some("execute"),
        "web_fetch" => Some("fetch"),
        "web_search" => Some("search"),
        _ => None,
    })
}
pub fn status(v: &Value) -> &'static str {
    match v.as_bool() {
        Some(true) => "failed",
        Some(false) => "completed",
        None => "unknown",
    }
}
pub fn result(
    s: &Spool,
    c: &mut Context,
    id: Option<&str>,
    status: &str,
    body: Option<&Value>,
) -> Result<()> {
    let mut r = json!({"type":"tool_result","status":status});
    if let Some(id) = id {
        r["callId"] = json!(id);
    }
    if let Some(b) = body {
        r["content"] = json!(parts(b, c));
    }
    c.result(s, r)
}
#[allow(clippy::too_many_arguments)]
pub fn message(
    s: &Spool,
    c: &mut Context,
    role: &str,
    body: &Value,
    author: Option<&str>,
    id: Option<&str>,
    fold: Option<&str>,
    inf: Option<&str>,
) -> Result<()> {
    if !matches!(role, "user" | "assistant" | "system" | "developer") {
        return Ok(());
    }
    let mut r = json!({"type":"message","role":role,"content":parts(body,c)});
    if let Some(a) = author {
        r["author"] = json!(a);
        if a == "human" {
            r["origin"] = json!("prompt");
        }
    }
    if let Some(i) = inf {
        r["inferenceId"] = json!(i);
    }
    if body.is_null() {
        c.loss("message_content");
    }
    c.emit(s, r, id, fold)
}
pub fn compaction(s: &Spool, c: &mut Context, body: Option<&Value>, lost: bool) -> Result<()> {
    if let Some(body) = body {
        c.emit(s,json!({"type":"message","role":"user","author":"harness","origin":"compaction","content":parts(body,c)}),None,None)?;
    }
    if lost {
        c.loss("compaction_history");
        c.emit(s, json!({"type":"gap","reason":"not_retained"}), None, None)?;
    }
    Ok(())
}
pub fn usage(u: &Value, fields: [&str; 5], add_cache: bool) -> Value {
    let mut r = json!({});
    for (dst, src) in [
        "inputTokens",
        "outputTokens",
        "cacheReadTokens",
        "cacheWriteTokens",
        "reasoningTokens",
    ]
    .into_iter()
    .zip(fields)
    {
        if let Some(n) = count(&u[src]) {
            r[dst] = json!(n);
        }
    }
    if add_cache {
        let cache = |field| match u.get(field) {
            None => Some(0),
            Some(value) => count(value),
        };
        if let (Some(base), Some(read), Some(write)) =
            (count(&u[fields[0]]), cache(fields[2]), cache(fields[3]))
        {
            let total = base + read + write;
            if total <= 9_007_199_254_740_991 {
                r["inputTokens"] = json!(total);
            } else {
                r.as_object_mut().unwrap().remove("inputTokens");
            }
        } else {
            r.as_object_mut().unwrap().remove("inputTokens");
        }
    }
    r
}
pub fn inference(s: &Spool, c: &mut Context, id: &str, mut r: Value) -> Result<()> {
    r["type"] = json!("inference");
    if !r["model"]["id"].is_string() && !r["model"]["requested"].is_string() {
        r.as_object_mut().unwrap().remove("model");
        c.loss("model");
    }
    c.emit(s, r, Some(id), Some(&format!("inference:{id}")))
}
pub fn tools(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if let Some(a) = v.as_array() {
        let tools: Vec<_> = a
            .iter()
            .filter_map(|t| {
                let mut r = json!({"name":t["name"].as_str()?});
                common::copy(&mut r, "description", t, "description");
                if let Some(schema) = t
                    .get("inputSchema")
                    .or_else(|| t.get("input_schema"))
                    .or_else(|| t.get("parameters"))
                {
                    r["inputSchema"] = schema.clone();
                }
                Some(r)
            })
            .collect();
        c.info(s, json!({"type":"session_info","tools":tools}))?;
    }
    Ok(())
}
pub fn approval(
    s: &Spool,
    c: &mut Context,
    v: &Value,
    call: Option<&str>,
    native: Option<&str>,
    by: Option<&str>,
) -> Result<()> {
    let choice = v["decision"].as_str().or_else(|| v["kind"].as_str());
    let decision = match choice {
        Some("approved" | "approved-for-session" | "allow" | "allow_once" | "allow_session") => {
            "approved"
        }
        Some("denied" | "rejected" | "deny") => "denied",
        Some("cancelled" | "expired") => "cancelled",
        _ => return Ok(()),
    };
    let mut r = json!({"type":"approval","decision":decision,"native":v});
    if let Some(id) = call {
        r["callId"] = json!(id);
    } else if let Some(subject) = v["subject"].as_str() {
        r["subject"] = json!(subject);
    }
    if let Some(by) = by {
        r["by"] = json!(by);
    }
    if decision != "cancelled" {
        if choice == Some("approved-for-session") || v["scope"] == "session" {
            r["scope"] = json!("session");
        } else if v["scope"] == "once" || choice == Some("allow_once") {
            r["scope"] = json!("once");
        }
    }
    c.emit(s, r, native, None)
}
/// Anthropic-style journal blocks without a claim about model-call boundaries.
pub fn blocks(s: &Spool, c: &mut Context, v: &Value, role: &str, body: &Value) -> Result<()> {
    let id = native_id(v);
    let content = parts(body, c);
    let is_blocks = body.as_array().is_some_and(|a| {
        a.iter()
            .any(|b| matches!(b["type"].as_str(), Some("tool_use" | "tool_result")))
    });
    if !content.is_empty() || !is_blocks {
        message(
            s,
            c,
            role,
            body,
            (role == "assistant").then_some("model"),
            id,
            None,
            None,
        )?;
    }
    for p in body.as_array().into_iter().flatten() {
        match p["type"].as_str() {
            Some("tool_use") if role == "assistant" => call(
                s,
                c,
                string(&p["id"]),
                p["name"].as_str(),
                p.get("input"),
                true,
                None,
                None,
                None,
            )?,
            Some("tool_result") => result(
                s,
                c,
                string(&p["tool_use_id"]),
                status(&p["is_error"]),
                p.get("content"),
            )?,
            _ => {}
        }
    }
    Ok(())
}
