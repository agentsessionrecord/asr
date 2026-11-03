//! LangGraph message writes. Checkpoint state is never searched recursively for chat.
use crate::{
    common::{self, Context},
    spool::Spool,
    sqlite as q, Error, Result,
};
use rmpv::Value as Packed;
use rusqlite::Connection;
use serde_json::{json, Map, Value};
pub(crate) fn stage(db: &Connection, s: &Spool, id: &str) -> Result<()> {
    q::rows(
        db,
        "writes",
        Some(("thread_id", id)),
        &["checkpoint_ns", "checkpoint_id", "task_id", "idx"],
        s.limit,
        |mut row| {
            if row.get("_gap").is_some() {
                return q::push(s, id, "write", row);
            }
            let decoded = if row["type"] == "null" {
                Some(Value::Null)
            } else if row["type"] == "msgpack" {
                q::blob(&row["value"]).and_then(|b| decode(&b).ok())
            } else {
                None
            };
            let Some(value) = decoded else {
                return q::gap(s, id, "unparseable");
            };
            row["value"] = value.clone();
            if row["channel"] == "messages" && row["checkpoint_ns"] == "" {
                let items = value
                    .as_array()
                    .map(Vec::as_slice)
                    .unwrap_or(std::slice::from_ref(&value));
                for item in items {
                    let body = if item["msgpackExt"] == 5 {
                        let args = &item["value"];
                        if args[0]
                            .as_str()
                            .is_some_and(|v| v.starts_with("langchain_core.messages"))
                            && matches!(
                                args[1].as_str(),
                                Some(
                                    "HumanMessage"
                                        | "AIMessage"
                                        | "ToolMessage"
                                        | "SystemMessage"
                                        | "RemoveMessage"
                                )
                            )
                        {
                            args.get(2)
                        } else {
                            None
                        }
                    } else {
                        Some(item)
                    };
                    if let Some(body) = body.filter(|v| v.is_object()) {
                        q::push(s, id, "message", body.clone())?;
                    } else {
                        q::gap(s, id, "unparseable")?;
                    }
                }
            } else {
                q::push(s, id, "write", row)?;
            }
            Ok(())
        },
    )?;
    q::rows(
        db,
        "checkpoints",
        Some(("thread_id", id)),
        &["checkpoint_ns", "checkpoint_id"],
        s.limit,
        |mut row| {
            for field in ["checkpoint", "metadata"] {
                if let Some(bytes) = q::blob(&row[field]) {
                    row[field] = if field == "metadata" {
                        std::str::from_utf8(&bytes)
                            .ok()
                            .and_then(|b| asr_core::jsonl::decode(b).ok())
                            .unwrap_or(Value::Null)
                    } else {
                        decode(&bytes).unwrap_or(Value::Null)
                    };
                }
            }
            q::push(s, id, "checkpoint", row)
        },
    )
}
pub(crate) fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if q::common(s, c, v)? {
        return Ok(());
    }
    c.loss("messagepack_binary_fields");
    let d = &v["data"];
    if v["table"] != "message" {
        return q::vendor(s, c, v);
    }
    let role = match d["type"].as_str().or_else(|| d["role"].as_str()) {
        Some("human") => "user",
        Some("ai") => "assistant",
        Some(r) => r,
        None => "",
    };
    if role == "remove" {
        c.loss("context_removals");
        return q::vendor(s, c, v);
    }
    let id = d["id"].as_str();
    let inf = if role == "assistant" && d["usage_metadata"].is_object() {
        Some(asr_core::identity::derive_id(&[
            &c.session,
            &id.map(str::to_owned)
                .unwrap_or_else(|| format!("position:{}", c.ordinal)),
            "inference",
        ]))
    } else {
        None
    };
    if role == "tool" {
        let status = match d["status"].as_str() {
            Some("success") => "completed",
            Some("error") => "failed",
            _ => "unknown",
        };
        q::result(
            s,
            c,
            d["tool_call_id"].as_str(),
            status,
            Some(json!(common::parts(&d["content"], c.agent))),
            id,
        )?;
    } else if matches!(role, "user" | "assistant" | "system" | "developer") {
        let mut r =
            json!({"type":"message","role":role,"content":common::parts(&d["content"],c.agent)});
        if role == "assistant" {
            r["author"] = json!("model");
        }
        if let Some(inf) = &inf {
            r["inferenceId"] = json!(inf);
        }
        c.emit(s, r, id, id.map(|id| format!("message:{id}")).as_deref())?;
        for (i, t) in d["tool_calls"].as_array().into_iter().flatten().enumerate() {
            let native = t["id"].as_str();
            let mut r = json!({"type":"tool_call","callId":native.map(str::to_owned).unwrap_or_else(||asr_core::identity::derive_id(&[&c.session,&c.ordinal.to_string(),&i.to_string(),"call"])),"requestedBy":"model"});
            common::copy(&mut r, "name", t, "name");
            if let Some(args) = t.get("args") {
                r["input"] = args.clone();
            }
            if let Some(inf) = &inf {
                r["inferenceId"] = json!(inf);
            }
            let fold = id
                .zip(native)
                .map(|(id, call)| format!("message-call:{id}:{call}:{i}"));
            c.emit(s, r, None, fold.as_deref())?;
        }
    }
    if let Some(inf) = inf {
        let u = &d["usage_metadata"];
        let mut usage = q::usage(u, "input_tokens", "output_tokens", "", "", true);
        for (target, source) in [
            ("cacheReadTokens", "/input_token_details/cache_read"),
            ("cacheWriteTokens", "/input_token_details/cache_creation"),
            ("reasoningTokens", "/output_token_details/reasoning"),
        ] {
            if let Some(n) = u.pointer(source).and_then(q::count) {
                usage[target] = json!(n);
            }
        }
        let mut r = json!({"type":"inference","usage":usage});
        if let Some(model) = d["response_metadata"]["model_name"].as_str() {
            r["model"] = json!({"id":model});
        }
        common::copy(
            &mut r,
            "stopReason",
            &d["response_metadata"],
            "finish_reason",
        );
        q::metadata(&mut r, c.agent, "response", &d["response_metadata"]);
        c.emit(s, r, Some(&inf), Some(&format!("inference:{inf}")))?;
    }
    q::vendor(s, c, v)
}
fn decode(bytes: &[u8]) -> Result<Value> {
    let mut cursor = std::io::Cursor::new(bytes);
    let value = rmpv::decode::read_value(&mut cursor)
        .map_err(|_| Error::Invalid("invalid MessagePack".into()))?;
    if cursor.position() != bytes.len() as u64 {
        return Err(Error::Invalid("trailing MessagePack bytes".into()));
    }
    unpack(value, 0)
}
fn unpack(v: Packed, depth: u32) -> Result<Value> {
    if depth > 100 {
        return Err(Error::Invalid("nested MessagePack limit".into()));
    }
    Ok(match v {
        Packed::Nil => Value::Null,
        Packed::Boolean(v) => json!(v),
        Packed::Integer(v) => {
            if let Some(n) = v.as_i64() {
                json!(n)
            } else {
                json!(v.as_u64())
            }
        }
        Packed::F32(v) if v.is_finite() => json!(v),
        Packed::F64(v) if v.is_finite() => json!(v),
        Packed::String(v) => json!(v
            .as_str()
            .ok_or_else(|| Error::Invalid("invalid MessagePack string".into()))?),
        Packed::Binary(_) => json!({"binaryOmitted":true}),
        Packed::Array(v) => Value::Array(
            v.into_iter()
                .map(|v| unpack(v, depth + 1))
                .collect::<Result<_>>()?,
        ),
        Packed::Map(v) => {
            let mut map = Map::new();
            for (k, v) in v {
                let key = k
                    .as_str()
                    .ok_or_else(|| Error::Invalid("nonstring MessagePack key".into()))?;
                if map.insert(key.into(), unpack(v, depth + 1)?).is_some() {
                    return Err(Error::Invalid("duplicate MessagePack key".into()));
                }
            }
            Value::Object(map)
        }
        Packed::Ext(tag, bytes) => {
            let mut cursor = std::io::Cursor::new(&bytes);
            let nested = rmpv::decode::read_value(&mut cursor)
                .ok()
                .filter(|_| cursor.position() == bytes.len() as u64);
            match nested {
                Some(v) => json!({"msgpackExt":tag,"value":unpack(v,depth+1)?}),
                None => json!({"msgpackExt":tag,"binaryOmitted":true}),
            }
        }
        _ => return Err(Error::Invalid("nonfinite MessagePack number".into())),
    })
}
