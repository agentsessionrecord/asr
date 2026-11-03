//! Warp local protobuf cache. Display text stays separate from model-facing evidence.
mod proto;
mod wire;
use crate::{
    common::{self, Context},
    spool::Spool,
    sqlite as q, Result,
};
use proto::Fields;
use rusqlite::Connection;
use serde_json::{json, Value};
pub(crate) fn stage(db: &Connection, s: &Spool, id: &str, row: &Value) -> Result<()> {
    q::rows(
        db,
        "agent_tasks",
        Some(("conversation_id", id)),
        &["task_id"],
        s.limit,
        |r| {
            if r.get("_gap").is_some() {
                return q::push(s, id, "task", r);
            }
            let Some(bytes) = q::blob(&r["task"]) else {
                return q::gap(s, id, "unparseable");
            };
            let fields = match Fields::parse(&bytes) {
                Ok(f) => f,
                Err(_) => return q::gap(s, id, "unparseable"),
            };
            for bytes in fields.all(5) {
                match project(bytes) {
                    Ok(v) => q::push(s, id, "record", v)?,
                    Err(_) => q::gap(s, id, "unparseable")?,
                }
            }
            // Undecoded binary is excluded because it can conceal credential values.
            q::diagnostic(s, "unsupported_binary_fields")?;
            Ok(())
        },
    )?;
    let mut row = row.clone();
    if let Some(mut data) = q::parse(&row["conversation_data"]) {
        if let Some(o) = data.as_object_mut() {
            o.remove("server_conversation_token");
            o.remove("forked_from_server_conversation_token");
        }
        row["conversation_data"] = data;
    }
    q::push(s, id, "state", row)
}
fn project(bytes: &[u8]) -> Result<Value> {
    let f = Fields::parse(bytes)?;
    let Some((kind, b)) = f.oneof(|n| matches!(n,2..=6|9|10|15..=28)) else {
        return Ok(json!({"vendorVariant":"unknown"}));
    };
    let p = Fields::parse(&b)?;
    let mut r = match kind {
        2 => {
            json!({"type":"message","role":"user","content":p.text(1)?.map(|t|vec![common::text(t)]).unwrap_or_default()})
        }
        3 | 15 => {
            let mut r = json!({"type":"message","role":"assistant","author":"model","content":[]});
            if let Some(text) = p.text(1)? {
                q::metadata(
                    &mut r,
                    crate::Agent::Warp,
                    "displayContent",
                    &json!([if kind == 15 {
                        common::reasoning(Some(text), None)
                    } else {
                        common::text(text)
                    }]),
                );
            }
            r
        }
        4 => {
            let mut r = json!({"type":"tool_call","requestedBy":"model"});
            if let Some(id) = p.text(1)? {
                r["callId"] = json!(id);
            }
            if let Some((kind, b)) = p.oneof(wire::is_warp_tool_arm) {
                let t = Fields::parse(&b)?;
                if kind == 12 {
                    if let Some(name) = t.text(1)? {
                        r["name"] = json!(name);
                    }
                    if let Some(args) = t.merged(2) {
                        r["input"] = proto::object(&args, 0)?;
                    }
                } else {
                    let name = wire::warp_tool_name(kind);
                    if name != "unknown" {
                        r["name"] = json!(name);
                    }
                    if kind == 2 {
                        if let Some(command) = t.text(1)? {
                            r["input"] = json!({"command":command});
                            r["kind"] = json!("execute");
                        }
                    }
                }
            }
            r
        }
        5 => {
            let mut r = json!({"type":"tool_result","status":"unknown"});
            if let Some(id) = p.text(1)? {
                r["callId"] = json!(id);
            }
            if let Some((kind, b)) = p.oneof(wire::is_warp_tool_result_arm) {
                let t = Fields::parse(&b)?;
                match kind {
                    14 => r["status"] = json!("cancelled"),
                    2 => {
                        let mut exec = json!({});
                        if let Some(output) = t.text(1)? {
                            exec["output"] = json!(output);
                        }
                        if let Some(command) = t.text(3)? {
                            exec["command"] = json!(command);
                        }
                        if let Some(code) = t.int(2) {
                            exec["exitCode"] = json!(code as i32);
                        }
                        r["exec"] = exec;
                        if let Some((state, _)) = t.oneof(|n| (4..=6).contains(&n)) {
                            if state == 5 {
                                r["status"] = json!("completed");
                            } else if state == 6 {
                                r["status"] = json!("denied");
                            }
                        }
                    }
                    16 => {
                        if let Some((state, b)) = t.oneof(|n| n == 1 || n == 2) {
                            let response = Fields::parse(&b)?;
                            r["status"] = json!(if state == 1 { "completed" } else { "failed" });
                            if state == 2 {
                                if let Some(text) = response.text(1)? {
                                    r["error"] = json!({"message":text});
                                }
                            } else {
                                let mut raw = Vec::new();
                                for content in response.all(1) {
                                    let content = Fields::parse(content)?;
                                    if let Some((1, b)) = content.oneof(|n| (1..=3).contains(&n)) {
                                        if let Some(text) = Fields::parse(&b)?.text(1)? {
                                            raw.push(common::text(text));
                                        }
                                    }
                                }
                                q::metadata(&mut r, crate::Agent::Warp, "rawContent", &json!(raw));
                            }
                        }
                    }
                    _ => {}
                }
            }
            r
        }
        16 => {
            let mut r = json!({"vendorVariant":"summary"});
            if let Some((1, b)) = p.oneof(|n| n == 1 || n == 3) {
                if let Some(text) = Fields::parse(&b)?.text(1)? {
                    r = json!({"type":"message","role":"user","author":"harness","origin":"compaction","content":[common::text(text)]});
                }
            }
            r
        }
        _ => json!({"vendorVariant":kind}),
    };
    if let Some(id) = f.text(1)?.filter(|s| !s.is_empty()) {
        r["id"] = json!(id);
    }
    if let Some(timestamp) = f.merged(14) {
        let t = Fields::parse(&timestamp)?;
        let seconds = t.int(1).unwrap_or(0) as i64;
        let nanos = t.int(2).unwrap_or(0);
        if nanos < 1_000_000_000 && (-62_135_596_800..=253_402_300_799).contains(&seconds) {
            if let Some(t) = chrono::DateTime::from_timestamp(seconds, nanos as u32) {
                r["ts"] = json!(t.to_rfc3339_opts(chrono::SecondsFormat::Nanos, true));
            }
        }
    }
    Ok(r)
}
pub(crate) fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if q::common(s, c, v)? {
        return Ok(());
    }
    c.loss("protobuf_fields");
    c.loss("model_facing_output");
    let d = &v["data"];
    if v["table"] == "record" && d["type"].is_string() {
        let mut r = d.clone();
        let id = r
            .as_object_mut()
            .unwrap()
            .remove("id")
            .and_then(|v| v.as_str().map(str::to_owned));
        if r["type"] == "tool_call" && r["callId"].as_str().is_none() {
            r["callId"] = json!(asr_core::identity::derive_id(&[
                &c.session,
                &c.ordinal.to_string(),
                "call"
            ]));
        }
        if r["type"] == "tool_result" {
            q::receipt(s, c, r, id.as_deref(), None)?;
        } else {
            c.emit(s, r, id.as_deref(), None)?;
        }
    } else if v["table"] == "state" {
        q::state(s, c, d)?;
    }
    q::vendor(s, c, v)
}
