//! Bounded document and relational sources share the reference staging pipeline.
use crate::{
    common::{self, Context},
    privacy,
    spool::{gap, Spool},
    Agent, Result, Summary,
};
use asr_core::{
    identity::derive_id,
    jsonl::{decode, Line, Reader},
};
use chrono::{DateTime, SecondsFormat, Utc};
use rusqlite::{types::ValueRef, Connection, OpenFlags};
use serde_json::{json, Value};
use std::{
    fs::File,
    io::{BufReader, Read},
    path::{Path, PathBuf},
};

pub fn handles(agent: Agent) -> bool {
    matches!(
        agent,
        Agent::Auggie
            | Agent::Cline
            | Agent::CodeBuddy
            | Agent::Continue
            | Agent::Hermes
            | Agent::NanoClaw
            | Agent::OpenHands
            | Agent::RooCode
            | Agent::RovoDev
    )
}
pub fn discover(
    input: &Path,
    out: &Path,
    agent: Agent,
    mut visit: impl FnMut(PathBuf) -> Result<()>,
) -> Result<()> {
    if input.is_file() {
        return visit(input.to_owned());
    }
    for entry in walkdir::WalkDir::new(input)
        .follow_links(false)
        .max_open(16)
        .sort_by(|a, b| natural_key(a.path()).cmp(&natural_key(b.path())))
        .into_iter()
        .filter_entry(|e| e.path() != out)
    {
        let entry = entry
            .map_err(|_| crate::Error::Invalid("source directory could not be read".into()))?;
        if !entry.file_type().is_file() {
            continue;
        }
        let path = entry.path();
        let name = entry.file_name().to_string_lossy();
        let selected = match agent {
            Agent::Hermes => name == "state.db",
            Agent::NanoClaw => name == "v2.db",
            Agent::Cline | Agent::RooCode => {
                matches!(
                    name.as_ref(),
                    "api_conversation_history.json" | "claude_messages.json" | "ui_messages.json"
                ) || name.ends_with(".messages.json")
            }
            Agent::CodeBuddy => {
                name.ends_with(".jsonl")
                    || name == "index.json"
                        && path.parent().is_some_and(|p| p.join("messages").is_dir())
            }
            Agent::OpenHands => {
                name.ends_with(".json")
                    && (path
                        .parent()
                        .and_then(Path::file_name)
                        .is_some_and(|p| p == "events")
                        || name.starts_with("event-")
                            && path
                                .parent()
                                .and_then(Path::parent)
                                .and_then(Path::file_name)
                                .is_some_and(|p| p == "v1_conversations"))
            }
            Agent::RovoDev => name == "session_context.json",
            _ => name.ends_with(".json"),
        };
        if selected {
            visit(path.to_owned())?;
        }
    }
    Ok(())
}
pub(crate) fn natural_key(path: &Path) -> (String, u64, String) {
    let name = path
        .file_name()
        .unwrap_or_default()
        .to_string_lossy()
        .into_owned();
    let numeric = name
        .split(['.', '-'])
        .find_map(|s| s.parse().ok())
        .unwrap_or(0);
    (
        path.parent()
            .unwrap_or(Path::new(""))
            .to_string_lossy()
            .into_owned(),
        numeric,
        name,
    )
}
pub fn stage(s: &mut Spool, agent: Agent, path: &Path, summary: &mut Summary) -> Result<()> {
    let canonical = std::fs::canonicalize(path)?;
    if s.db.execute(
        "INSERT OR IGNORE INTO sources VALUES(?1)",
        [canonical.to_string_lossy().as_ref()],
    )? == 0
    {
        return Ok(());
    }
    summary.files += 1;
    match agent {
        Agent::Hermes => crate::hermes::stage(s, path, summary),
        Agent::NanoClaw => crate::nanoclaw::stage(s, path, summary),
        Agent::CodeBuddy => crate::codebuddy::stage(s, path, summary),
        _ => {
            let Some(value) = read(s, path, summary)? else {
                if let Some((id, native)) = stored_identity(s, agent, path, summary)? {
                    header(s, agent, &id, &native, summary)?;
                    store(s, &id, "gap", &Value::Null)?;
                }
                return Ok(());
            };
            match agent {
                Agent::Auggie => crate::auggie::stage(s, path, &value, summary),
                Agent::Cline => crate::cline::stage(s, path, &value, summary),
                Agent::RooCode => crate::roo_code::stage(s, path, &value, summary),
                Agent::Continue => crate::continue_cli::stage(s, path, &value, summary),
                Agent::OpenHands => crate::openhands::stage(s, path, &value, summary),
                Agent::RovoDev => crate::rovodev::stage(s, path, &value, summary),
                _ => unreachable!(),
            }
        }
    }
}
fn stored_identity(
    s: &mut Spool,
    agent: Agent,
    path: &Path,
    summary: &mut Summary,
) -> Result<Option<(String, Value)>> {
    let Some(directory) = path.parent() else {
        return Ok(None);
    };
    let sidecar = match agent {
        Agent::Cline | Agent::RooCode => Some("task_metadata.json"),
        Agent::RovoDev => Some("metadata.json"),
        _ => None,
    };
    if let Some(sidecar) = sidecar {
        let source = directory.join(sidecar);
        if source.is_file() {
            if let Some(native) = read(s, &source, summary)? {
                let keys = if agent == Agent::RovoDev {
                    &["session_id", "sessionId"][..]
                } else {
                    &["id", "taskId", "task_id"][..]
                };
                if let Some(id) = string(&native, keys) {
                    return Ok(Some((id, native)));
                }
            }
        }
    }
    let native_directory = match agent {
        Agent::Cline | Agent::RooCode
            if directory
                .parent()
                .and_then(Path::file_name)
                .is_some_and(|n| n == "tasks") =>
        {
            Some(directory)
        }
        Agent::OpenHands if directory.file_name().is_some_and(|n| n == "events") => {
            directory.parent()
        }
        Agent::OpenHands
            if directory
                .parent()
                .and_then(Path::file_name)
                .is_some_and(|n| n == "v1_conversations") =>
        {
            Some(directory)
        }
        _ => None,
    };
    Ok(native_directory
        .and_then(Path::file_name)
        .and_then(|n| n.to_str())
        .map(|id| (id.to_owned(), Value::Null)))
}
pub fn read(s: &mut Spool, path: &Path, summary: &mut Summary) -> Result<Option<Value>> {
    let mut bytes = Vec::new();
    File::open(path)?
        .take((s.limit + 1) as u64)
        .read_to_end(&mut bytes)?;
    summary.source_bytes += bytes.len() as u64;
    let value = (bytes.len() <= s.limit)
        .then(|| {
            std::str::from_utf8(&bytes)
                .ok()
                .and_then(|r| decode(r).ok())
        })
        .flatten();
    match value {
        Some(mut v) => {
            sanitize(s, &mut v, summary)?;
            Ok(Some(v))
        }
        None => {
            summary.diagnostic("unparseable_source_document");
            Ok(None)
        }
    }
}
pub fn sanitize(s: &mut Spool, value: &mut Value, summary: &mut Summary) -> Result<()> {
    // Structured credentials are found before native values reach disk.
    privacy::questions(s, value)?;
    privacy::answers(s, value)?;
    s.has_secrets =
        s.db.query_row("SELECT EXISTS(SELECT 1 FROM secrets)", [], |r| r.get(0))?;
    if redact(s, value)? {
        summary.diagnostic("secret_redacted");
    }
    privacy::scrub_opaque(value, false);
    Ok(())
}
fn redact(s: &Spool, value: &mut Value) -> Result<bool> {
    let changed = match value {
        Value::Object(o) => {
            let mut changed = false;
            for v in o.values_mut() {
                changed |= redact(s, v)?;
            }
            if changed {
                o.insert("_asrRedacted".into(), json!(true));
            }
            changed
        }
        Value::Array(a) => {
            let mut changed = false;
            for v in a {
                changed |= redact(s, v)?;
            }
            changed
        }
        _ => privacy::sanitize(s, value)?,
    };
    Ok(changed)
}
pub fn jsonl(
    s: &mut Spool,
    path: &Path,
    summary: &mut Summary,
    mut visit: impl FnMut(&mut Spool, Value, &mut Summary) -> Result<()>,
) -> Result<()> {
    // First pass finds secret questions and values before anything reaches disk.
    let mut reader = Reader::new(BufReader::new(File::open(path)?), s.limit);
    while let Some(line) = reader.read()? {
        if let Line::Record(v) = line {
            privacy::questions(s, &v)?;
        }
    }
    let mut reader = Reader::new(BufReader::new(File::open(path)?), s.limit);
    while let Some(line) = reader.read()? {
        if let Line::Record(v) = line {
            privacy::answers(s, &v)?;
        }
    }
    let mut reader = Reader::new(BufReader::new(File::open(path)?), s.limit);
    while let Some(line) = reader.read()? {
        match line {
            Line::Record(mut v) => {
                sanitize(s, &mut v, summary)?;
                visit(s, v, summary)?;
            }
            Line::Incomplete => summary.diagnostic("incomplete_source_tail"),
            _ => {
                summary.diagnostic("unparseable_source_line");
                visit(s, json!({"_gap":true}), summary)?;
            }
        }
    }
    summary.source_bytes += reader.bytes;
    Ok(())
}
/// Aliases agree exactly or supply no fact.
pub fn alias<'a>(v: &'a Value, keys: &[&str]) -> Option<&'a Value> {
    let mut selected = None;
    for key in keys {
        if let Some(x) = v.get(*key) {
            if selected.is_some_and(|old| old != x) {
                return None;
            }
            selected = Some(x);
        }
    }
    selected
}
pub fn string(v: &Value, keys: &[&str]) -> Option<String> {
    alias(v, keys)?
        .as_str()
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
}
pub fn scalar(v: &Value) -> Option<String> {
    match v {
        Value::String(s) if !s.is_empty() => Some(s.clone()),
        Value::Number(n) => Some(n.to_string()),
        _ => None,
    }
}
pub fn timestamp(value: &Value) -> Option<String> {
    if let Some(text) = value.as_str() {
        if DateTime::parse_from_rfc3339(text).is_ok() {
            return Some(text.to_owned());
        }
    }
    let raw = value
        .as_str()
        .map(str::to_owned)
        .unwrap_or_else(|| value.to_string());
    // Decimal arithmetic avoids inventing fractional nanoseconds through f64.
    let (whole, fraction) = raw.split_once('.').unwrap_or((&raw, ""));
    let integer: i64 = whole.parse().ok()?;
    let precision = if integer.unsigned_abs() >= 10_000_000_000 {
        6 // Epoch milliseconds can supply six fractional digits at nanosecond precision.
    } else {
        9
    };
    if !fraction.bytes().all(|b| b.is_ascii_digit()) || fraction.len() > precision {
        return None;
    }
    let fraction_nanos = if fraction.is_empty() {
        0
    } else {
        fraction.parse::<i128>().ok()? * 10i128.pow((precision - fraction.len()) as u32)
    };
    let whole_nanos = i128::from(integer) * 10i128.pow(precision as u32);
    let total = if raw.starts_with('-') {
        whole_nanos - fraction_nanos
    } else {
        whole_nanos + fraction_nanos
    };
    let secs = i64::try_from(total.div_euclid(1_000_000_000)).ok()?;
    let nanos = total.rem_euclid(1_000_000_000) as u32;
    DateTime::<Utc>::from_timestamp(secs, nanos)
        .map(|t| t.to_rfc3339_opts(SecondsFormat::AutoSi, true))
}
pub fn time(v: &Value) -> Option<String> {
    [
        "timestamp",
        "ts",
        "createdAt",
        "created_at",
        "time",
        "finishedAt",
    ]
    .iter()
    .find_map(|key| v.get(*key).and_then(timestamp))
}
pub fn header(
    s: &mut Spool,
    agent: Agent,
    id: &str,
    native: &Value,
    summary: &mut Summary,
) -> Result<()> {
    let mut h = common::header(agent, id);
    h["missing"]
        .as_array_mut()
        .unwrap()
        .extend(["reasoning", "native_history"].map(|loss| json!(loss)));
    if let Some(cwd) = string(native, &["cwd"])
        .or_else(|| string(native, &["workspaceDirectory"]))
        .or_else(|| string(native, &["workspaceRoot", "workspace_root"]))
    {
        if common::absolute(&cwd) {
            h["cwd"] = json!(cwd);
        }
    }
    for key in ["title", "agentVersion"] {
        if let Some(value) = native[key].as_str() {
            if key == "title" {
                h[key] = json!(value);
            } else {
                h["agent"]["version"] = json!(value);
            }
        }
    }
    if let Some(t) = [
        "startedAt",
        "started_at",
        "createdAt",
        "created_at",
        "created",
    ]
    .iter()
    .find_map(|k| native.get(*k).and_then(timestamp))
    {
        h["startedAt"] = json!(t);
    }
    crate::repository::capture(&mut h, agent, native);
    sanitize(s, &mut h, summary)?;
    s.session(id, &h)
}
pub fn parent(s: &Spool, id: &str, agent: Agent, parent: &str, kind: &str) -> Result<()> {
    let mut h: Value =
        s.db.query_row("SELECT header FROM sessions WHERE id=?1", [id], |r| {
            r.get::<_, String>(0)
        })
        .map(|raw| serde_json::from_str(&raw))??;
    h["parent"] =
        json!({"session":asr_core::identity::session_ref(agent.name(),None,parent),"kind":kind});
    s.db.execute(
        "UPDATE sessions SET header=?2 WHERE id=?1",
        rusqlite::params![id, h.to_string()],
    )?;
    Ok(())
}
pub fn store(s: &Spool, id: &str, kind: &str, value: &Value) -> Result<()> {
    s.push(
        id,
        &json!({"kind":kind,"value":value,"_asrRedacted":value["_asrRedacted"]==true}),
        None,
    )
}
pub fn record(s: &Spool, id: &str, record: Value, native: &Value) -> Result<()> {
    store(
        s,
        id,
        "record",
        &json!({"record":record,"native":native,"_asrRedacted":native["_asrRedacted"]==true}),
    )
}
pub fn metadata(s: &Spool, id: &str, v: &Value, arrays: &[&str]) -> Result<()> {
    let mut v = v.clone();
    if let Some(o) = v.as_object_mut() {
        for key in arrays {
            o.remove(*key);
        }
    }
    store(s, id, "metadata", &v)
}
pub fn project(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    let native = &v["value"];
    c.source = json!({});
    if let Some(ts) = time(native) {
        c.source["ts"] = json!(ts);
    }
    match v["kind"].as_str() {
        Some("record") => {
            let mut r = native["record"].clone();
            if r.get("ts").is_none() {
                if let Some(ts) = time(&native["native"]) {
                    r["ts"] = json!(ts);
                }
            }
            r["_meta"] = json!({c.agent.domain():{"native":native["native"]}});
            let id = scalar(&native["native"]["id"]);
            if r["type"] == "tool_result" {
                if let Some(id) = id {
                    r["id"] = json!(id);
                }
                c.result(s, r)
            } else {
                c.emit(s, r, id.as_deref(), None)
            }
        }
        Some("message") => chat(s, c, native),
        Some("gap") => {
            c.loss("native_history");
            c.emit(s, gap("unparseable"), None, None)
        }
        _ => c.vendor(s, native),
    }
}
pub fn status(v: &Value) -> &'static str {
    if let Some(error) = v["is_error"].as_bool() {
        return if error { "failed" } else { "completed" };
    }
    match alias(v, &["status", "state", "outcome"])
        .and_then(Value::as_str)
        .or_else(|| v["finish_reason"].as_str())
    {
        Some("completed" | "complete" | "success" | "succeeded" | "done") => "completed",
        Some("failed" | "failure" | "error") => "failed",
        Some("denied" | "rejected") => "denied",
        Some("cancelled" | "canceled") => "cancelled",
        Some("interrupted") => "interrupted",
        _ => "unknown",
    }
}
fn emit_native(
    s: &Spool,
    c: &mut Context,
    mut record: Value,
    native: &Value,
    id: Option<&str>,
) -> Result<()> {
    record["_meta"] = json!({c.agent.domain():{"native":native}});
    if record["type"] == "tool_result" {
        if let Some(id) = id {
            record["id"] = json!(id);
        }
        c.result(s, record)
    } else {
        c.emit(s, record, id, None)
    }
}
pub fn call(s: &Spool, c: &mut Context, v: &Value, model: bool) -> Result<()> {
    let fun = v.get("function").unwrap_or(v);
    let id = string(v, &["call_id", "callId", "tool_call_id", "tool_use_id"])
        .or_else(|| scalar(&v["id"]))
        .unwrap_or_else(|| {
            derive_id(&[
                &c.session,
                &c.ordinal.to_string(),
                &c.slot.to_string(),
                "call",
            ])
        });
    let mut r = json!({"type":"tool_call","callId":id});
    if model {
        r["requestedBy"] = json!("model");
    }
    if let Some(name) = string(fun, &["name", "tool_name", "tool"]) {
        r["name"] = json!(name);
        if let Some(kind) = common::kind(&name) {
            r["kind"] = json!(kind);
        }
    }
    if let Some(input) = alias(fun, &["input", "arguments", "parameters", "args"]) {
        if let Some(raw) = input.as_str() {
            if let Ok(mut parsed) = decode(raw) {
                asr_core::jsonl::stringify_large_native(&mut parsed);
                r["input"] = parsed;
            } else {
                r["inputText"] = json!(raw);
            }
        } else {
            r["input"] = input.clone();
        }
    }
    emit_native(s, c, r, v, scalar(&v["id"]).as_deref())
}
pub fn result(s: &Spool, c: &mut Context, v: &Value, content: &Value) -> Result<()> {
    let mut r =
        json!({"type":"tool_result","status":status(v),"content":content_parts(content,c.agent)});
    if let Some(id) = string(
        v,
        &[
            "tool_call_id",
            "tool_use_id",
            "call_id",
            "callId",
            "toolCallId",
        ],
    ) {
        r["callId"] = json!(id);
    }
    if let Some(exit) = alias(v, &["exitCode", "exit_code"]).and_then(Value::as_i64) {
        r["exec"] = json!({"exitCode":exit});
    }
    if let Some(duration) = v["durationMs"]
        .as_number()
        .filter(|n| n.as_f64().is_some_and(|n| n >= 0.0))
    {
        r["durationMs"] = json!(duration);
    }
    emit_native(s, c, r, v, scalar(&v["id"]).as_deref())
}
fn content_parts(v: &Value, agent: Agent) -> Vec<Value> {
    if v.is_null() {
        return Vec::new();
    }
    common::parts(v, agent)
}
pub fn chat(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    c.source = json!({});
    if let Some(t) = time(v) {
        c.source["ts"] = json!(t);
    }
    if v["_gap"] == true {
        return c.emit(s, gap("unparseable"), None, None);
    }
    let initial_slot = c.slot;
    let role = v["role"]
        .as_str()
        .or_else(|| v["type"].as_str())
        .unwrap_or("");
    let content = v.get("content").or_else(|| v.get("text"));
    if matches!(role, "tool" | "tool_result" | "function_result") {
        return result(s, c, v, content.unwrap_or(&Value::Null));
    }
    if !matches!(role, "user" | "assistant" | "system" | "developer") {
        return c.vendor(s, v);
    }
    let native_id = scalar(&v["id"]).or_else(|| scalar(&v["uuid"]));
    let mut text = Vec::new();
    let flush = |c: &mut Context, text: &mut Vec<Value>| -> Result<()> {
        if text.is_empty() {
            return Ok(());
        }
        let mut r = json!({"type":"message","role":role,"content":std::mem::take(text)});
        if role == "assistant" {
            r["author"] = json!("model");
        }
        if matches!(role, "system" | "developer") {
            r["origin"] = json!("instructions");
        }
        for key in ["author", "origin", "phase"] {
            if let Some(value) = v[key].as_str() {
                r[key] = json!(value);
            }
        }
        emit_native(s, c, r, v, native_id.as_deref())
    };
    if let Some(content) = content {
        if let Some(parts) = content.as_array() {
            for p in parts {
                match p["type"].as_str() {
                    Some("tool_use" | "tool_call" | "function_call") => {
                        flush(c, &mut text)?;
                        call(s, c, p, role == "assistant")?;
                    }
                    Some("tool_result" | "tool_output") => {
                        flush(c, &mut text)?;
                        result(
                            s,
                            c,
                            p,
                            p.get("content")
                                .or_else(|| p.get("output"))
                                .unwrap_or(&Value::Null),
                        )?;
                    }
                    _ => {
                        if p.is_string() {
                            text.push(common::text(p.as_str().unwrap()));
                        } else {
                            text.extend(common::parts(&json!([p]), c.agent));
                        }
                    }
                }
            }
        } else if content.is_string() {
            text = content_parts(content, c.agent);
        } else {
            c.loss("content");
        }
        if content.as_array().is_some_and(Vec::is_empty) || content.as_str() == Some("") {
            emit_native(
                s,
                c,
                json!({"type":"message","role":role,"content":content_parts(content,c.agent)}),
                v,
                native_id.as_deref(),
            )?;
        }
    }
    flush(c, &mut text)?;
    for call_value in v["tool_calls"].as_array().into_iter().flatten() {
        call(s, c, call_value, role == "assistant")?;
    }
    if c.slot == initial_slot {
        c.loss("content");
        c.vendor(s, v)?;
    }
    Ok(())
}
pub fn sqlite(path: &Path) -> Result<Connection> {
    let db = Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )?;
    db.execute_batch(
        "PRAGMA query_only=ON; PRAGMA trusted_schema=OFF; PRAGMA cache_size=-4096; BEGIN;",
    )?;
    Ok(db)
}
pub fn table(db: &Connection, name: &str) -> Result<bool> {
    Ok(db.query_row(
        "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name=?1)",
        [name],
        |r| r.get(0),
    )?)
}
fn quote(s: &str) -> String {
    format!("\"{}\"", s.replace('"', "\"\""))
}
pub fn rows(
    db: &Connection,
    table: &str,
    s: &mut Spool,
    summary: &mut Summary,
    mut visit: impl FnMut(&mut Spool, Value, &mut Summary) -> Result<()>,
) -> Result<()> {
    let mut schema = db.prepare(&format!("PRAGMA table_info({})", quote(table)))?;
    let columns = schema
        .query_map([], |r| r.get::<_, String>(1))?
        .collect::<std::result::Result<Vec<_>, _>>()?;
    if columns.is_empty() {
        return Err(crate::Error::Invalid(
            "required native table is absent".into(),
        ));
    }
    let size = columns
        .iter()
        .map(|c| format!("coalesce(length(CAST({} AS BLOB)),0)", quote(c)))
        .collect::<Vec<_>>()
        .join("+");
    let projected = columns
        .iter()
        .map(|c| format!("CASE WHEN ({size})<=?1 THEN {} END", quote(c)))
        .collect::<Vec<_>>()
        .join(",");
    let mut stmt = db.prepare(&format!(
        "SELECT rowid, {size}, {projected} FROM {} ORDER BY rowid",
        quote(table)
    ))?;
    let mut cursor = stmt.query([s.limit as u64])?;
    while let Some(row) = cursor.next()? {
        let source_rowid: i64 = row.get(0)?;
        let size: u64 = row.get(1)?;
        summary.source_bytes += size;
        if size > s.limit as u64 {
            summary.diagnostic("oversized_source_row");
            let mut v = json!({"_gap":true});
            // Bounded identity columns can still locate the missing row.
            for name in ["id", "session_id"] {
                if columns.iter().any(|c| c == name) {
                    let sql=format!("SELECT CASE WHEN length(CAST({} AS BLOB))<=1024 THEN CAST({} AS TEXT) END FROM {} WHERE rowid=?1",quote(name),quote(name),quote(table));
                    let identity: Option<String> =
                        db.query_row(&sql, [source_rowid], |r| r.get(0))?;
                    if let Some(identity) = identity {
                        v[name] = json!(identity);
                    }
                }
            }
            visit(s, v, summary)?;
            continue;
        }
        let mut value = json!({});
        let mut corrupt = false;
        for (i, name) in columns.iter().enumerate() {
            value[name] = match row.get_ref(i + 2)? {
                ValueRef::Null => Value::Null,
                ValueRef::Integer(n) => json!(n),
                ValueRef::Real(n) => json!(n),
                ValueRef::Text(b) => match std::str::from_utf8(b) {
                    Ok(t) => json!(t),
                    Err(_) => {
                        summary.diagnostic("invalid_source_text");
                        corrupt = true;
                        Value::Null
                    }
                },
                ValueRef::Blob(_) => {
                    summary.diagnostic("unsupported_source_blob");
                    corrupt = true;
                    Value::Null
                }
            };
        }
        if corrupt {
            value["_gap"] = json!(true);
        }
        sanitize(s, &mut value, summary)?;
        visit(s, value, summary)?;
    }
    Ok(())
}
