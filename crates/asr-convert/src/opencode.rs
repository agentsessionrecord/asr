//! OpenCode-family stored rows and sequenced v2 entries.
use crate::{
    common::{self, Context},
    spool::Spool,
    sqlite as q, Result,
};
use rusqlite::Connection;
use serde_json::{json, Value};
pub(crate) fn stage(db: &Connection, s: &Spool, id: &str, row: &Value) -> Result<()> {
    let mut current = None;
    for table in ["session_message", "session_entry"] {
        if q::has(db, table)?
            && db.query_row(
                &format!("SELECT EXISTS(SELECT 1 FROM {table} WHERE session_id=?1)"),
                [id],
                |r| r.get::<_, bool>(0),
            )?
        {
            current = Some(table);
            break;
        }
    }
    if let Some(table) = current {
        q::rows(
            db,
            table,
            Some(("session_id", id)),
            &["seq", "time_created", "id"],
            s.limit,
            |v| stage_data(s, id, "event", v),
        )?;
    }
    q::rows(
        db,
        "message",
        Some(("session_id", id)),
        &["time_created", "id"],
        s.limit,
        |v| {
            let migrated = if let (Some(t), Some(native)) = (current, v["id"].as_str()) {
                db.query_row(
                    &format!("SELECT EXISTS(SELECT 1 FROM {t} WHERE session_id=?1 AND id=?2)"),
                    rusqlite::params![id, native],
                    |r| r.get::<_, bool>(0),
                )?
            } else {
                false
            };
            let table = if migrated { "legacy" } else { "message" };
            let message = v["id"].as_str().map(str::to_owned);
            let fallback = v.clone();
            let mut has_step = false;
            if let Some(message) = &message {
                q::rows(
                    db,
                    "part",
                    Some(("message_id", message)),
                    &["id"],
                    s.limit,
                    |v| {
                        has_step |=
                            q::parse(&v["data"]).is_some_and(|p| p["type"] == "step-finish");
                        Ok(())
                    },
                )?;
            }
            let single_inference = (!has_step
                && v["data"]
                    .as_str()
                    .and_then(|v| serde_json::from_str::<Value>(v).ok())
                    .is_some_and(|d| d["role"] == "assistant" && d["tokens"].is_object()))
            .then(|| {
                asr_core::identity::derive_id(&[id, message.as_deref().unwrap_or(""), "inference"])
            });
            stage_data(s, id, table, v)?;
            if let Some(message) = message {
                q::rows(
                    db,
                    "part",
                    Some(("message_id", &message)),
                    &["id"],
                    s.limit,
                    |mut v| {
                        if v["session_id"].as_str().is_none_or(|x| x == id) {
                            if let Some(inference) = &single_inference {
                                v["_asrSingleInference"] = json!(inference);
                            }
                            stage_data(s, id, if migrated { "legacy" } else { "part" }, v)?;
                        }
                        Ok(())
                    },
                )?;
            }
            if !migrated && !has_step {
                stage_data(s, id, "usage", fallback)?;
            }
            Ok(())
        },
    )?;
    let has_messages = q::has(db, "message")?;
    q::rows(
        db,
        "part",
        Some(("session_id", id)),
        &["id"],
        s.limit,
        |v| {
            let owned = if let Some(message) = v["message_id"].as_str().filter(|_| has_messages) {
                db.query_row(
                    "SELECT EXISTS(SELECT 1 FROM message WHERE id=?1 AND session_id=?2)",
                    rusqlite::params![message, id],
                    |r| r.get::<_, bool>(0),
                )?
            } else {
                false
            };
            if !owned {
                stage_data(s, id, "orphan_part", v)?;
            }
            Ok(())
        },
    )?;
    if q::has(db, "session_v2")? && q::has(db, "session")? {
        let legacy = q::one(db, "session", "id", id, s.limit)?;
        if !legacy.is_null() {
            q::push(s, id, "legacy_session", legacy)?;
        }
    }
    for table in [
        "todo",
        "session_input",
        "session_context_epoch",
        "session_context_snapshot",
    ] {
        if q::columns(db, table)?.iter().any(|c| c == "session_id") {
            q::rows(
                db,
                table,
                Some(("session_id", id)),
                &["position", "id"],
                s.limit,
                |v| q::push(s, id, table, v),
            )?;
        }
    }
    q::push(s, id, "state", row.clone())
}
fn stage_data(s: &Spool, id: &str, table: &str, mut row: Value) -> Result<()> {
    if row.get("_gap").is_some() {
        return q::push(s, id, table, row);
    }
    let Some(mut data) = q::parse(&row["data"]).filter(Value::is_object) else {
        return q::gap(s, id, "unparseable");
    };
    if table == "event" && row["type"].is_string() {
        data["type"] = row["type"].clone();
    }
    row["data"] = data;
    q::push(s, id, table, row)
}
fn tokens(t: &Value) -> Value {
    let flat = json!({"input":t["input"],"output":t["output"],"read":t["cache"]["read"],"write":t["cache"]["write"]});
    let mut u = q::usage(&flat, "input", "output", "read", "write", false);
    if let Some(reasoning) = q::count(&t["reasoning"]) {
        u["reasoningTokens"] = json!(reasoning);
        if let Some(out) = q::count(&t["output"])
            .and_then(|x| x.checked_add(reasoning))
            .filter(|x| *x <= q::SAFE)
        {
            u["outputTokens"] = json!(out);
        }
    }
    u
}
fn inference(s: &Spool, c: &mut Context, id: &str, d: &Value, model: &Value) -> Result<String> {
    let key = asr_core::identity::derive_id(&[&c.session, id, "inference"]);
    let mut r = json!({"type":"inference","usage":tokens(&d["tokens"])});
    let requested = model["modelID"].as_str().or_else(|| d["modelID"].as_str());
    if let Some(requested) = requested {
        r["model"] = json!({"requested":requested});
        if let Some(provider) = model["providerID"]
            .as_str()
            .or_else(|| d["providerID"].as_str())
        {
            r["model"]["provider"] = json!(provider);
        }
    }
    if let Some(cost) = q::cost(&d["cost"], "harness_estimated") {
        r["cost"] = cost;
    }
    if let Some(reason) = d["reason"].as_str().or_else(|| d["finish"].as_str()) {
        r["stopReason"] = json!(reason);
    }
    q::stamp(&mut r, &d["time"]["completed"], true);
    c.emit(s, r, Some(&key), Some(&format!("inference:{key}")))?;
    Ok(key)
}
fn part_content(d: &Value) -> Option<Value> {
    match d["type"].as_str(){
    Some("text") if d["ignored"]!=true=>d["text"].as_str().map(common::text),
    Some("reasoning")=>Some(common::reasoning(d["text"].as_str(),None)),
    Some("file")=>d["url"].as_str().map(|u|json!({"type":"resource_link","uri":u,"name":d["filename"].as_str().unwrap_or("file")})),
    _=>None
}
}
fn message(s: &Spool, c: &mut Context, row: &Value, d: &Value, split: bool) -> Result<()> {
    let Some(id) = row["id"].as_str() else {
        return Ok(());
    };
    let role = d["role"]
        .as_str()
        .or_else(|| d["type"].as_str())
        .or_else(|| row["type"].as_str())
        .unwrap_or("");
    if !matches!(
        role,
        "user" | "assistant" | "system" | "developer" | "synthetic"
    ) {
        return Ok(());
    }
    let mut r =
        json!({"type":"message","role":if role=="synthetic"{"user"}else{role},"content":[]});
    if role == "assistant" {
        r["author"] = json!("model");
        if let Some(agent) = d["agent"].as_str() {
            c.settings(s, json!({"mode":agent}))?;
        }
    }
    if role == "synthetic" {
        r["author"] = json!("harness");
        r["origin"] = json!("injected");
    }
    if d.pointer("/metadata/schedule").is_some() {
        r["origin"] = json!("scheduled");
    }
    if d["error"].is_object() {
        r["status"] = json!("error");
    } else if d["time"]["completed"].is_number() {
        r["status"] = json!("complete");
    }
    let mut content = Vec::new();
    if let Some(text) = d["text"].as_str() {
        content.push(common::text(text));
    }
    for p in d["content"].as_array().into_iter().flatten() {
        if let Some(p) = part_content(p) {
            content.push(p);
        }
    }
    r["content"] = json!(content);
    q::stamp(&mut r, &d["time"]["completed"], true);
    if r.get("ts").is_none() {
        q::stamp(&mut r, &row["time_created"], true);
    }
    q::metadata(&mut r, c.agent, "message", d);
    if split {
        s.save(&format!("opencode-message:{id}"), &r)?;
        s.save(&format!("opencode-model:{id}"), d)?;
    }
    c.emit(
        s,
        r,
        Some(id),
        split.then(|| format!("message:{id}")).as_deref(),
    )?;
    if !split {
        for p in d["content"].as_array().into_iter().flatten() {
            if p["type"] == "tool" {
                tool(s, c, p, None, None)?;
            }
        }
        if role == "assistant" && d["tokens"].is_object() {
            inference(s, c, id, d, &d["model"])?;
        }
    }
    Ok(())
}
fn tool(
    s: &Spool,
    c: &mut Context,
    d: &Value,
    native: Option<&str>,
    inference: Option<&str>,
) -> Result<()> {
    let Some(id) = d["callID"].as_str().or_else(|| d["id"].as_str()) else {
        return Ok(());
    };
    let state = &d["state"];
    let name = d["tool"].as_str().or_else(|| d["name"].as_str());
    let mut call = json!({"type":"tool_call","callId":id,"requestedBy":"model"});
    if let Some(name) = name {
        call["name"] = json!(name);
        if let Some(kind) = match name {
            "edit" | "write" => Some("edit"),
            "read" => Some("read"),
            "bash" => Some("execute"),
            _ => None,
        } {
            call["kind"] = json!(kind);
        }
    }
    if let Some(args) = state.get("input") {
        q::input(&mut call, args);
    }
    if let Some(inference) = inference {
        call["inferenceId"] = json!(inference);
    }
    q::stamp(&mut call, &state["time"]["start"], true);
    c.emit(s, call, native, None)?;
    let status = match state["status"].as_str() {
        Some("completed") => "completed",
        Some("error") => "failed",
        _ => return Ok(()),
    };
    let error = &state["error"];
    let mut result = json!({"type":"tool_result","callId":id,"status":status});
    if let Some(out) = state["output"].as_str() {
        result["content"] = json!([common::text(out)]);
    }
    if let Some(error) = error.as_str() {
        result["error"] = json!({"message":error});
    } else if error.is_object() {
        let mut value = json!({});
        common::copy(&mut value, "message", error, "message");
        common::copy(&mut value, "code", error, "type");
        result["error"] = value;
    }
    q::stamp(&mut result, &state["time"]["end"], true);
    if let Some(child) = state["metadata"]["sessionId"].as_str() {
        result["subagent"] = json!({"session":asr_core::identity::session_ref(c.agent.name(),c.namespace.as_deref(),child)});
    }
    q::receipt(
        s,
        c,
        result,
        None,
        native.map(|id| format!("result-part:{id}")).as_deref(),
    )?;
    if matches!(name, Some("edit" | "write")) {
        let meta = &state["metadata"];
        let args = &state["input"];
        let path = args["filePath"]
            .as_str()
            .or_else(|| meta["filepath"].as_str());
        if let Some(path) = path {
            let mut change = json!({"type":"file_change","path":common::path(path,c.cwd.as_deref()),"op":if name==Some("write")&&meta["exists"]==false{"add"}else{"modify"},"status":if status=="completed"{"applied"}else{"failed"},"callId":id});
            if let Some(patch) = meta["diff"]
                .as_str()
                .or_else(|| meta["filediff"]["patch"].as_str())
            {
                change["patch"] = json!(patch);
            } else if name == Some("edit") && status == "completed" {
                if let (Some(old), Some(new)) =
                    (args["oldString"].as_str(), args["newString"].as_str())
                {
                    if args["replaceAll"] != true {
                        change["edits"] = json!([{"oldText":old,"newText":new}]);
                    } else {
                        c.loss("edit_repetitions");
                    }
                }
            }
            c.emit(s, change, None, None)?;
        }
    }
    Ok(())
}
pub(crate) fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if q::common(s, c, v)? {
        return Ok(());
    }
    let row = &v["data"];
    let d = &row["data"];
    match v["table"].as_str() {
        Some("state") => {
            q::state(s, c, row)?;
            let mut settings = json!({});
            common::copy(&mut settings, "mode", row, "agent");
            if let Some(p) = row.get("permission") {
                settings["approval"] = q::parse(p).unwrap_or_else(|| p.clone());
            }
            c.settings(s, settings)?;
        }
        Some("usage") => {
            if d["role"] == "assistant" && d["tokens"].is_object() {
                inference(s, c, row["id"].as_str().unwrap_or(""), d, &d["model"])?;
            }
        }
        Some("message") => message(s, c, row, d, true)?,
        Some("part") => {
            if let Some(part) = part_content(d) {
                if let Some(id) = row["message_id"].as_str() {
                    if let Some(mut m) = s.entity(&format!("opencode-message:{id}"))? {
                        m["content"].as_array_mut().unwrap().push(part);
                        m.as_object_mut().unwrap().remove("ts");
                        q::stamp(&mut m, &d["time"]["end"], true);
                        s.save(&format!("opencode-message:{id}"), &m)?;
                        c.emit(s, m, Some(id), Some(&format!("message:{id}")))?;
                    }
                }
            }
            if d["type"] == "tool" {
                tool(
                    s,
                    c,
                    d,
                    row["id"].as_str(),
                    row["_asrSingleInference"].as_str(),
                )?;
            }
            if d["type"] == "step-finish" {
                let model = s
                    .entity(&format!(
                        "opencode-model:{}",
                        row["message_id"].as_str().unwrap_or("")
                    ))?
                    .unwrap_or(Value::Null);
                inference(s, c, row["id"].as_str().unwrap_or(""), d, &model)?;
            }
            if d["type"] == "compaction" {
                c.emit(s,json!({"type":"gap","reason":"not_retained","detail":"The snapshot retains a compaction marker without its replaced history."}),None,None)?;
            }
        }
        Some("event") => match d["type"].as_str().or_else(|| row["type"].as_str()) {
            Some("user" | "assistant" | "system" | "synthetic") => message(s, c, row, d, false)?,
            Some("agent-switched") => c.settings(s, json!({"mode":d["agent"]}))?,
            Some("model-switched") => {
                c.loss("configured_model_selection");
            }
            Some("compaction") => {
                if let Some(summary) = d["summary"].as_str() {
                    c.emit(s,json!({"type":"message","role":"user","author":"harness","origin":"compaction","content":[common::text(summary)]}),row["id"].as_str(),None)?;
                }
                c.emit(s, json!({"type":"gap","reason":"not_retained"}), None, None)?;
            }
            _ => {}
        },
        _ => {}
    }
    q::vendor(s, c, v)
}
