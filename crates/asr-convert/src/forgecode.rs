//! ForgeCode persisted context entries, including flattened MessageEntry variants.
use crate::{
    common::{self, Context},
    spool::Spool,
    sqlite as q, Result,
};
use rusqlite::Connection;
use serde_json::{json, Value};
pub(crate) fn stage(_db: &Connection, s: &Spool, id: &str, row: &Value) -> Result<()> {
    if row.get("_gap").is_some() {
        return q::push(s, id, "state", row.clone());
    }
    let Some(mut body) = q::parse(&row["context"]) else {
        return q::gap(s, id, "unparseable");
    };
    match body.as_object_mut().and_then(|o| o.remove("messages")) {
        Some(Value::Array(messages)) => {
            for m in messages {
                q::push(s, id, "message", m)?;
            }
        }
        _ => q::gap(s, id, "unparseable")?,
    }
    let mut row = q::without(row, &["context"]);
    row["context"] = body;
    q::push(s, id, "state", row)
}
pub(crate) fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if q::common(s, c, v)? {
        return Ok(());
    }
    let d = &v["data"];
    if v["table"] == "state" {
        q::state(s, c, d)?;
        if let Some(tools) = d["context"]["tools"].as_array() {
            let tools: Vec<_> = tools
                .iter()
                .filter_map(|t| {
                    let name = t["name"].as_str()?;
                    let mut r = json!({"name":name});
                    common::copy(&mut r, "description", t, "description");
                    common::copy(&mut r, "inputSchema", t, "input_schema");
                    Some(r)
                })
                .collect();
            c.info(s, json!({"type":"session_info","tools":tools}))?;
        }
    } else {
        let entry = d.get("message").unwrap_or(d);
        if let Some(text) = entry.get("text") {
            let role = match text["role"].as_str() {
                Some("User") => "user",
                Some("Assistant") => "assistant",
                Some("System") => "system",
                Some(x) => x,
                None => "",
            };
            let mut m = text.clone();
            m["role"] = json!(role);
            q::message(s, c, &m)?;
            if role == "assistant" && d["usage"].is_object() {
                let u = &d["usage"];
                let mut usage = json!({});
                for (source, target) in [
                    ("completion_tokens", "outputTokens"),
                    ("cached_tokens", "cacheReadTokens"),
                ] {
                    if let Some(n) = q::count(&u[source]["Actual"]) {
                        usage[target] = json!(n);
                    }
                }
                // The native report does not state whether prompt tokens include cache hits.
                c.loss("usage_cache_inclusion");
                let mut r = json!({"type":"inference","usage":usage});
                if let Some(model) = text["model"].as_str() {
                    r["model"] = json!({"id":model});
                }
                q::metadata(&mut r, c.agent, "usage", u);
                c.emit(s, r, None, None)?;
            }
            for detail in text["reasoning_details"].as_array().into_iter().flatten() {
                if let Some(t) = detail["text"].as_str() {
                    let p = if detail["type_of"] == "reasoning.summary" {
                        json!({"type":"reasoning","visibility":"summary","summary":[t]})
                    } else {
                        common::reasoning(Some(t), None)
                    };
                    c.emit(
                        s,
                        json!({"type":"message","role":"assistant","author":"model","content":[p]}),
                        None,
                        None,
                    )?;
                } else if detail["type_of"] == "reasoning.encrypted" {
                    c.emit(s,json!({"type":"message","role":"assistant","author":"model","content":[{"type":"reasoning","visibility":"encrypted"}]}),None,None)?;
                }
            }
        } else if let Some(tool) = entry.get("tool") {
            let mut content = Vec::new();
            for item in tool["output"]["values"].as_array().into_iter().flatten() {
                if let Some(t) = item["text"]
                    .as_str()
                    .or_else(|| item["ai"]["value"].as_str())
                {
                    content.push(common::text(t));
                }
            }
            q::result(
                s,
                c,
                tool["call_id"].as_str(),
                q::error_status(&tool["output"]["is_error"]),
                Some(json!(content)),
                None,
            )?;
        }
    }
    q::vendor(s, c, v)
}
