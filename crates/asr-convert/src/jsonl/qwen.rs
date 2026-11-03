use super::helpers::*;
use crate::{
    common::{copy, Context},
    spool::Spool,
    Result,
};
use serde_json::{json, Value};
pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if v["type"] == "system" {
        if v["subtype"] == "custom_title" && v["systemPayload"]["customTitle"].is_string() {
            return c.info(
                s,
                json!({"type":"session_info","title":v["systemPayload"]["customTitle"]}),
            );
        }
        if v["subtype"] == "chat_compression"
            && v["systemPayload"]["info"]["compressionStatus"] == 1
        {
            return compaction(s, c, None, true);
        }
        return Ok(());
    }
    if !matches!(
        v["type"].as_str(),
        Some("user" | "assistant" | "tool_result")
    ) {
        return Ok(());
    }
    let body = v
        .pointer("/message/parts")
        .or_else(|| v.pointer("/message/content"))
        .unwrap_or(&v["content"]);
    let role = if v["type"] == "assistant" {
        "assistant"
    } else {
        "user"
    };
    let author = match v["provenance"].as_str() {
        Some("real_user") => Some("human"),
        Some("assistant_output") => Some("model"),
        Some("system" | "goal_control" | "goal_runtime") => Some("harness"),
        Some("tool_result") => Some("tool"),
        _ => {
            if role == "assistant" {
                Some("model")
            } else {
                None
            }
        }
    };
    if v["type"] != "tool_result" || !parts(body, c).is_empty() {
        message(s, c, role, body, author, native_id(v), None, None)?;
    }
    let mut result_seen = false;
    for p in body.as_array().into_iter().flatten() {
        if let Some(fc) = p.get("functionCall") {
            call(
                s,
                c,
                string(&fc["id"]),
                fc["name"].as_str(),
                fc.get("args"),
                role == "assistant",
                None,
                None,
                None,
            )?;
        }
        if let Some(fr) = p.get("functionResponse") {
            result_seen = true;
            let native = &v["toolCallResult"];
            let id = string(&fr["id"]).or_else(|| string(&native["callId"]));
            let mut r = json!({"type":"tool_result","status":match native["status"].as_str(){Some("success"|"completed")=>"completed",Some("error"|"failed")=>"failed",Some("cancelled")=>"cancelled",_=>"unknown"}});
            if let Some(id) = id {
                r["callId"] = json!(id);
            }
            meta(c, &mut r, "functionResponse", fr);
            meta(c, &mut r, "nativeResult", native);
            c.result(s, r)?;
        }
    }
    if !result_seen && v["type"] == "tool_result" {
        let native = &v["toolCallResult"];
        let mut r = json!({"type":"tool_result","status":"unknown"});
        copy(&mut r, "callId", native, "callId");
        meta(c, &mut r, "nativeResult", native);
        c.result(s, r)?;
    }
    if v.get("usageMetadata").is_some() {
        c.loss("usage_scope");
    }
    Ok(())
}
