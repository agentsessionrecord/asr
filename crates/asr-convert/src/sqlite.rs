//! Read-only native snapshots and bounded cursors for database adapters.
use crate::{
    common::{self, Context},
    spool::Spool,
    Agent, Error, Options, Result, Summary,
};
use asr_core::{
    identity::{derive_id, session_ref},
    jsonl::decode,
};
use base64::{engine::general_purpose::STANDARD, Engine};
use rusqlite::{types::ValueRef, Connection, OpenFlags, OptionalExtension};
use serde_json::{json, Value};
use std::{io::Read, path::Path};

pub(crate) fn handles(agent: Agent) -> bool {
    matches!(
        agent,
        Agent::AstrBot
            | Agent::Crush
            | Agent::Lingma
            | Agent::Shelley
            | Agent::DeepAgents
            | Agent::ForgeCode
            | Agent::OpenCode
            | Agent::Kilo
            | Agent::MimoCode
            | Agent::Zed
            | Agent::Devin
            | Agent::Firebender
            | Agent::Goose
            | Agent::Kiro
            | Agent::Warp
            | Agent::OpenClaw
    )
}

pub(crate) const SAFE: u64 = 9_007_199_254_740_991;
pub(crate) fn discover(
    s: &mut Spool,
    o: &Options,
    out: &Path,
    summary: &mut Summary,
) -> Result<()> {
    if o.namespace.as_ref().is_some_and(|n| n.is_empty()) {
        return Err(Error::Invalid("namespace must not be empty".into()));
    }
    if o.agent == Agent::Goose && o.namespace.is_none() {
        return Err(Error::Invalid(
            "Goose requires --namespace with a stable installation/profile identifier".into(),
        ));
    }
    s.db.execute_batch("CREATE TABLE IF NOT EXISTS database_owners(id TEXT PRIMARY KEY,path TEXT); CREATE TABLE IF NOT EXISTS database_diagnostics(code TEXT PRIMARY KEY,n INTEGER);")?;
    let mut visit = |path: &Path| -> Result<()> {
        if o.agent == Agent::OpenClaw
            && path
                .extension()
                .is_some_and(|e| e == "jsonl" || e == "zst" || e == "zstd")
        {
            return crate::source::stage(s, o.agent, path, summary);
        }
        let path = std::fs::canonicalize(path)?;
        if s.db.execute(
            "INSERT OR IGNORE INTO sources VALUES(?1)",
            [path.to_string_lossy().as_ref()],
        )? == 0
        {
            return Ok(());
        }
        summary.files += 1;
        summary.source_bytes += std::fs::metadata(&path)?.len();
        let db = Connection::open_with_flags(
            &path,
            OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )?;
        db.busy_timeout(std::time::Duration::from_secs(5))?;
        db.execute_batch("PRAGMA query_only=ON; PRAGMA cache_size=-4096; PRAGMA temp_store=FILE; PRAGMA mmap_size=0; BEGIN;")?;
        let (table, column) = match o.agent {
            Agent::Crush | Agent::Goose | Agent::Devin => ("sessions", "id"),
            Agent::AstrBot | Agent::ForgeCode => ("conversations", "conversation_id"),
            Agent::Shelley => ("conversations", "conversation_id"),
            Agent::Lingma => ("chat_record", "session_id"),
            Agent::Zed => ("threads", "id"),
            Agent::Firebender => ("chat_sessions", "id"),
            Agent::DeepAgents => ("checkpoints", "thread_id"),
            Agent::Warp => ("agent_conversations", "conversation_id"),
            Agent::OpenClaw => ("session_windows", "session_id"),
            Agent::OpenCode | Agent::Kilo | Agent::MimoCode => {
                if has(&db, "session_v2")? {
                    ("session_v2", "id")
                } else {
                    ("session", "id")
                }
            }
            Agent::Kiro => {
                return crate::kiro::stage(&db, s, o.namespace.as_deref(), &path, summary);
            }
            _ => return Ok(()),
        };
        if !has(&db, table)? {
            diagnostic(s, "unsupported_schema")?;
            return Ok(());
        }
        let sql = if o.agent == Agent::DeepAgents && has(&db, "writes")? {
            "SELECT thread_id AS native FROM checkpoints UNION SELECT thread_id FROM writes ORDER BY 1".into()
        } else if table == "session_v2" && has(&db, "session")? {
            "SELECT id AS native FROM session_v2 UNION SELECT id FROM session ORDER BY 1".into()
        } else {
            format!(
                "SELECT DISTINCT {} AS native FROM {} ORDER BY 1",
                quote(column),
                quote(table)
            )
        };
        let mut stmt = db.prepare(&format!("SELECT CASE WHEN typeof(native)='text' AND length(CAST(native AS BLOB))<=4096 THEN native END FROM ({sql})"))?;
        let mut cursor = stmt.query([])?;
        let mut identified = false;
        while let Some(row) = cursor.next()? {
            let Some(id) = row.get::<_, Option<String>>(0)?.filter(|s| !s.is_empty()) else {
                diagnostic(s, "unidentified_source")?;
                continue;
            };
            identified = true;
            let before_secret_bytes = s.secret_bytes.get();
            s.db.execute_batch("SAVEPOINT database_session")?;
            let staged = (|| -> Result<()> {
                owner(s, &id, &path)?;
                let actual =
                    if table == "session_v2" && one(&db, table, column, &id, s.limit)?.is_null() {
                        "session"
                    } else {
                        table
                    };
                let row = if matches!(o.agent, Agent::Lingma | Agent::DeepAgents) {
                    json!({})
                } else {
                    one(&db, actual, column, &id, s.limit)?
                };
                let mut header = header(o.agent, &id, o.namespace.as_deref());
                metadata(
                    &mut header,
                    o.agent,
                    "snapshot",
                    &without(
                        &row,
                        &[
                            "content",
                            "context",
                            "messages_json",
                            "data",
                            "row_transcript_json",
                        ],
                    ),
                );
                for key in ["cwd", "working_dir", "working_directory", "directory"] {
                    if let Some(cwd) = row[key].as_str().filter(|p| common::absolute(p)) {
                        header["cwd"] = json!(cwd);
                        break;
                    }
                }
                crate::repository::capture(&mut header, o.agent, &row);
                if let Some(version) = row["version"].as_str() {
                    header["agent"]["version"] = json!(version);
                }
                if let Some(t) = time(&row["time_created"], true) {
                    header["startedAt"] = json!(t);
                }
                if let Some(parent) = row["fork_session_id"].as_str() {
                    header["parent"] =
                        json!({"kind":"fork","session":reference(&header, o.agent, parent)});
                }
                s.session(&id, &header)?;
                match o.agent {
                    Agent::Crush => crate::crush::stage(&db, s, &id, &row)?,
                    Agent::Goose => crate::goose::stage(&db, s, &id, &row)?,
                    Agent::Lingma => crate::lingma::stage(&db, s, &id)?,
                    Agent::AstrBot => crate::astrbot::stage(&db, s, &id, &row)?,
                    Agent::Shelley => crate::shelley::stage(&db, s, &id, &row)?,
                    Agent::Zed => crate::zed::stage(&db, s, &id, &row)?,
                    Agent::OpenCode | Agent::Kilo | Agent::MimoCode => {
                        crate::opencode::stage(&db, s, &id, &row)?
                    }
                    Agent::Firebender => crate::firebender::stage(&db, s, &id, &row)?,
                    Agent::ForgeCode => crate::forgecode::stage(&db, s, &id, &row)?,
                    Agent::DeepAgents => crate::deepagents::stage(&db, s, &id)?,
                    Agent::Devin => crate::devin::stage(&db, s, &id, &row)?,
                    Agent::Warp => crate::warp::stage(&db, s, &id, &row)?,
                    Agent::OpenClaw => crate::openclaw::stage(&db, s, &id, &row, &path)?,
                    _ => unreachable!(),
                }
                Ok(())
            })();
            if let Err(error) = staged {
                s.db.execute_batch("ROLLBACK TO database_session; RELEASE database_session")?;
                s.has_secrets =
                    s.db.query_row("SELECT EXISTS(SELECT 1 FROM secrets)", [], |r| r.get(0))?;
                s.secret_bytes.set(before_secret_bytes);
                *s.secret_matcher.borrow_mut() = None;
                let h = header(o.agent, &id, o.namespace.as_deref());
                let code = match error {
                    Error::Session { code, .. } => code,
                    _ => "source_staging_failed",
                };
                summary.diagnostic_for(&reference(&h, o.agent, &id), code);
                s.db.execute("INSERT OR IGNORE INTO failed_sessions VALUES(?1)", [&id])?;
            } else {
                s.db.execute_batch("RELEASE database_session")?;
            }
        }
        if !identified {
            diagnostic(s, "empty_native_store")?;
        }
        Ok(())
    };
    discover_paths(o.agent, &o.input, out, |path| visit(&path))?;
    let mut stmt =
        s.db.prepare("SELECT code,n FROM database_diagnostics ORDER BY code")?;
    for row in stmt.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, u64>(1)?)))? {
        let (code, n) = row?;
        *summary.diagnostics.entry(code).or_default() += n;
    }
    s.db.execute("DELETE FROM database_diagnostics", [])?;
    Ok(())
}
pub(crate) fn owner(s: &Spool, id: &str, path: &Path) -> Result<()> {
    let previous: Option<String> =
        s.db.query_row("SELECT path FROM database_owners WHERE id=?1", [id], |r| {
            r.get(0)
        })
        .optional()?;
    if previous
        .as_deref()
        .is_some_and(|p| p != path.to_string_lossy())
    {
        return Err(Error::Session {
            session: id.into(),
            code: "colliding_session_identity",
        });
    }
    s.db.execute(
        "INSERT OR IGNORE INTO database_owners VALUES(?1,?2)",
        rusqlite::params![id, path.to_string_lossy()],
    )?;
    Ok(())
}
pub(crate) fn header(agent: Agent, id: &str, namespace: Option<&str>) -> Value {
    let mut h = common::header(agent, id);
    h["missing"] = json!([
        "approvals",
        "copies",
        "commits",
        "file_changes",
        "subagents",
        "tools",
        "agent_settings",
        "model",
        "usage",
        "timestamps",
        "inference_settings",
        "snapshot_history",
        "order",
        "native_binary_fields"
    ]);
    if agent == Agent::OpenClaw {
        h["producer"]["source"] = json!("openclaw-sqlite");
    }
    h["extensions"] = json!([format!("{}/native-sqlite", agent.domain())]);
    if let Some(namespace) = namespace {
        h["namespace"] = json!(namespace);
    }
    h
}
pub(crate) fn reference(h: &Value, agent: Agent, id: &str) -> String {
    session_ref(agent.name(), h["namespace"].as_str(), id)
}
pub(crate) fn quote(s: &str) -> String {
    format!("\"{}\"", s.replace('"', "\"\""))
}
pub(crate) fn has(db: &Connection, table: &str) -> Result<bool> {
    Ok(db.query_row(
        "SELECT EXISTS(SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?1)",
        [table],
        |r| r.get(0),
    )?)
}
pub(crate) fn columns(db: &Connection, table: &str) -> Result<Vec<String>> {
    let mut stmt = db.prepare("SELECT name FROM pragma_table_info(?1) ORDER BY cid")?;
    let cols = stmt
        .query_map([table], |r| r.get(0))?
        .collect::<rusqlite::Result<_>>()?;
    Ok(cols)
}
/// SQLite checks byte lengths before transferring large cells into Rust.
pub(crate) fn rows(
    db: &Connection,
    table: &str,
    filter: Option<(&str, &str)>,
    order: &[&str],
    limit: usize,
    mut visit: impl FnMut(Value) -> Result<()>,
) -> Result<()> {
    if !has(db, table)? {
        return Ok(());
    }
    let cols = columns(db, table)?;
    let size = cols
        .iter()
        .map(|c| format!("coalesce(length(CAST({} AS BLOB)),0)", quote(c)))
        .collect::<Vec<_>>()
        .join("+");
    let fields = cols
        .iter()
        .map(|c| format!("CASE WHEN ({size})<=?1 THEN {} END", quote(c)))
        .collect::<Vec<_>>()
        .join(",");
    let ordering = order
        .iter()
        .filter(|c| cols.iter().any(|x| x == **c))
        .map(|c| quote(c))
        .collect::<Vec<_>>();
    let ordering = if ordering.is_empty() {
        "rowid".into()
    } else {
        ordering.join(",")
    };
    let predicate = filter.map_or_else(String::new, |(col, _)| format!("WHERE {}=?2", quote(col)));
    let mut stmt = db.prepare(&format!(
        "SELECT ({size}),{fields} FROM {} {predicate} ORDER BY {ordering}",
        quote(table)
    ))?;
    let mut cursor = if let Some((_, id)) = filter {
        stmt.query(rusqlite::params![limit as u64, id])?
    } else {
        stmt.query([limit as u64])?
    };
    let mut ordinal = 0u64;
    while let Some(row) = cursor.next()? {
        ordinal += 1;
        let mut v = json!({"_table":table,"_ordinal":ordinal});
        if row.get::<_, u64>(0)? > limit as u64 {
            v["_gap"] = json!("not_retained");
        } else {
            for (i, c) in cols.iter().enumerate() {
                v[c] = match row.get_ref(i + 1)? {
                    ValueRef::Null => Value::Null,
                    ValueRef::Integer(n) => json!(n),
                    ValueRef::Real(n) => json!(n),
                    ValueRef::Text(b) => match std::str::from_utf8(b) {
                        Ok(t) => json!(t),
                        Err(_) => {
                            v["_gap"] = json!("unparseable");
                            Value::Null
                        }
                    },
                    ValueRef::Blob(b) => json!({"_blob":STANDARD.encode(b)}),
                };
            }
        }
        visit(v)?;
    }
    Ok(())
}
pub(crate) fn one(
    db: &Connection,
    table: &str,
    column: &str,
    id: &str,
    limit: usize,
) -> Result<Value> {
    let mut out = Value::Null;
    rows(db, table, Some((column, id)), &[], limit, |v| {
        out = v;
        Ok(())
    })?;
    Ok(out)
}
pub(crate) fn parse(v: &Value) -> Option<Value> {
    v.as_str().and_then(|s| decode(s).ok())
}
pub(crate) fn blob(v: &Value) -> Option<Vec<u8>> {
    v["_blob"]
        .as_str()
        .and_then(|b| STANDARD.decode(b).ok())
        .or_else(|| v.as_str().map(|s| s.as_bytes().to_vec()))
}
pub(crate) fn decompress(bytes: &[u8], limit: usize) -> Option<Vec<u8>> {
    let mut out = Vec::new();
    zstd::stream::read::Decoder::new(bytes)
        .ok()?
        .take(limit as u64 + 1)
        .read_to_end(&mut out)
        .ok()?;
    (out.len() <= limit).then_some(out)
}
pub(crate) fn diagnostic(s: &Spool, code: &str) -> Result<()> {
    s.db.execute(
        "INSERT INTO database_diagnostics VALUES(?1,1) ON CONFLICT(code) DO UPDATE SET n=n+1",
        [code],
    )?;
    Ok(())
}
pub(crate) fn push(s: &Spool, id: &str, table: &str, mut data: Value) -> Result<()> {
    if let Some(reason) = data["_gap"].as_str() {
        return gap(s, id, reason);
    }
    if omit_binary(&mut data) {
        diagnostic(s, "unsupported_binary_fields")?;
    }
    let value = json!({"table":table,"data":data});
    if value.to_string().len() > s.limit {
        return gap(s, id, "not_retained");
    }
    crate::privacy::questions(s, &value)?;
    s.push(id, &value, None)
}
pub(crate) fn gap(s: &Spool, id: &str, reason: &str) -> Result<()> {
    diagnostic(
        s,
        if reason == "unparseable" {
            "unparseable_source_row"
        } else {
            "oversized_source_row"
        },
    )?;
    s.push(id, &json!({"table":"_gap","data":{"reason":reason}}), None)
}
pub(crate) fn common(s: &Spool, c: &mut Context, v: &Value) -> Result<bool> {
    c.turn = None;
    c.source = json!({});
    if v["table"] == "_gap" {
        c.loss("source_rows");
        c.emit(
            s,
            json!({"type":"gap","reason":v["data"]["reason"],"count":1}),
            None,
            None,
        )?;
        return Ok(true);
    }
    Ok(false)
}
pub(crate) fn metadata(record: &mut Value, agent: Agent, key: &str, value: &Value) {
    if !value.is_null() {
        let mut value = value.clone();
        omit_binary(&mut value);
        record["_meta"][agent.domain()][key] = value;
    }
}
/// Only decoded native payloads reach privacy matching. Unknown blobs cannot be inspected.
fn omit_binary(v: &mut Value) -> bool {
    if v.get("_blob").is_some() {
        *v = json!({"binaryOmitted":true});
        return true;
    }
    match v {
        Value::Object(o) => o
            .values_mut()
            .fold(false, |changed, v| omit_binary(v) | changed),
        Value::Array(a) => a
            .iter_mut()
            .fold(false, |changed, v| omit_binary(v) | changed),
        _ => false,
    }
}
pub(crate) fn without(v: &Value, fields: &[&str]) -> Value {
    let mut v = v.clone();
    if let Some(o) = v.as_object_mut() {
        for key in fields {
            o.remove(*key);
        }
    }
    v
}
pub(crate) fn time(v: &Value, millis: bool) -> Option<String> {
    if millis {
        return common::timestamp_millis(v);
    }
    if let Some(t) = v.as_str() {
        return chrono::DateTime::parse_from_rfc3339(t)
            .ok()
            .map(|_| t.to_owned());
    }
    let n = v.as_i64()?;
    let d = if millis {
        chrono::DateTime::from_timestamp_millis(n)
    } else {
        chrono::DateTime::from_timestamp(n, 0)
    }?;
    (1..=9999)
        .contains(&chrono::Datelike::year(&d))
        .then(|| d.to_rfc3339_opts(chrono::SecondsFormat::Millis, true))
}
pub(crate) fn stamp(r: &mut Value, v: &Value, millis: bool) {
    if let Some(t) = time(v, millis) {
        r["ts"] = json!(t);
    }
}
pub(crate) use crate::common::count;
pub(crate) fn usage(
    v: &Value,
    input: &str,
    output: &str,
    read: &str,
    write: &str,
    inclusive: bool,
) -> Value {
    let mut u = json!({});
    for (key, src) in [
        ("cacheReadTokens", read),
        ("cacheWriteTokens", write),
        ("outputTokens", output),
    ] {
        if let Some(n) = count(&v[src]) {
            u[key] = json!(n);
        }
    }
    if let Some(n) = count(&v[input]) {
        let total = if inclusive {
            Some(n)
        } else {
            n.checked_add(count(&v[read]).unwrap_or(0))
                .and_then(|n| n.checked_add(count(&v[write]).unwrap_or(0)))
        };
        if let Some(n) = total.filter(|n| *n <= SAFE) {
            u["inputTokens"] = json!(n);
        }
    }
    u
}
pub(crate) fn cost(v: &Value, source: &str) -> Option<Value> {
    v.as_f64()
        .filter(|n| n.is_finite() && *n >= 0.0 && *n <= SAFE as f64)
        .map(|_| json!({"amount":v,"currency":"USD","source":source}))
}
pub(crate) fn input(r: &mut Value, v: &Value) {
    if let Some(t) = v.as_str() {
        if let Ok(mut x) = decode(t) {
            asr_core::jsonl::stringify_large_native(&mut x);
            r["input"] = x;
        } else {
            r["inputText"] = v.clone();
        }
    } else {
        r["input"] = v.clone();
    }
}
pub(crate) fn call(
    s: &Spool,
    c: &mut Context,
    id: Option<&str>,
    name: Option<&str>,
    args: Option<&Value>,
    native: Option<&str>,
    inference: Option<&str>,
) -> Result<()> {
    let id = id.map(str::to_owned).unwrap_or_else(|| {
        derive_id(&[
            &c.session,
            &c.ordinal.to_string(),
            &c.slot.to_string(),
            "call",
        ])
    });
    let mut r = json!({"type":"tool_call","callId":id});
    if let Some(name) = name {
        r["name"] = json!(name);
    }
    if let Some(args) = args {
        input(&mut r, args);
    }
    if let Some(inference) = inference {
        r["inferenceId"] = json!(inference);
    }
    c.emit(s, r, native, None)
}
pub(crate) fn result(
    s: &Spool,
    c: &mut Context,
    id: Option<&str>,
    status: &str,
    content: Option<Value>,
    native: Option<&str>,
) -> Result<()> {
    let mut r = json!({"type":"tool_result","status":status});
    if let Some(id) = id {
        r["callId"] = json!(id);
    }
    if let Some(content) = content {
        r["content"] = content;
    }
    let key = native.map(|id| format!("result-item:{id}"));
    receipt(s, c, r, native, key.as_deref())
}
pub(crate) fn error_status(v: &Value) -> &'static str {
    match v.as_bool() {
        Some(true) => "failed",
        Some(false) => "completed",
        None => "unknown",
    }
}
pub(crate) fn message(s: &Spool, c: &mut Context, m: &Value) -> Result<()> {
    let role = m["role"].as_str().unwrap_or("");
    let native = m["id"].as_str().or_else(|| m["message_id"].as_str());
    if role == "tool" {
        result(
            s,
            c,
            m["tool_call_id"].as_str(),
            error_status(&m["is_error"]),
            m.get("content").map(|x| json!(common::parts(x, c.agent))),
            native,
        )?;
    } else if matches!(role, "user" | "assistant" | "system" | "developer") {
        let mut r =
            json!({"type":"message","role":role,"content":common::parts(&m["content"],c.agent)});
        if role == "assistant" {
            r["author"] = json!("model");
        }
        if matches!(role, "system" | "developer") {
            r["origin"] = json!("instructions");
        }
        stamp(&mut r, &m["timestamp"], true);
        c.emit(s, r, native, None)?;
        for t in m["tool_calls"].as_array().into_iter().flatten() {
            let f = t.get("function").unwrap_or(t);
            call(
                s,
                c,
                t["id"].as_str().or_else(|| t["call_id"].as_str()),
                f["name"].as_str(),
                f.get("arguments").or_else(|| t.get("args")),
                None,
                None,
            )?;
        }
    }
    Ok(())
}
pub(crate) fn vendor(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    c.vendor(s, v)
}
pub(crate) fn state(s: &Spool, c: &mut Context, row: &Value) -> Result<()> {
    for key in ["cwd", "working_dir", "working_directory", "directory"] {
        if let Some(cwd) = row[key].as_str().filter(|p| common::absolute(p)) {
            c.cwd = Some(cwd.into());
            break;
        }
    }
    let mut info = json!({"type":"session_info"});
    for k in ["title", "name", "slug"] {
        if let Some(title) = row[k].as_str() {
            info["title"] = json!(title);
            break;
        }
    }
    if info.get("title").is_some() {
        c.info(s, info)?;
    }
    Ok(())
}
pub(crate) fn update_header(s: &Spool, id: &str, update: impl FnOnce(&mut Value)) -> Result<()> {
    let raw: String =
        s.db.query_row("SELECT header FROM sessions WHERE id=?1", [id], |r| {
            r.get(0)
        })?;
    let mut h: Value = serde_json::from_str(&raw)?;
    update(&mut h);
    crate::privacy::questions(s, &h)?;
    s.db.execute(
        "UPDATE sessions SET header=?1 WHERE id=?2",
        rusqlite::params![h.to_string(), id],
    )?;
    Ok(())
}

/// Independent receipts with a reused call ID cannot be paired safely.
pub(crate) fn receipt(
    s: &Spool,
    c: &mut Context,
    mut r: Value,
    native: Option<&str>,
    fold: Option<&str>,
) -> Result<()> {
    if r["type"] != "tool_result" {
        return c.emit(s, r, native, fold);
    }
    if let Some(call) = r["callId"].as_str().map(str::to_owned) {
        let key = format!("receipt-link:{call}");
        if let Some(previous) = s.entity(&key)? {
            let same = fold.is_some_and(|f| previous["fold"].as_str() == Some(f));
            if !same || previous["ambiguous"] == true {
                c.loss("ambiguous_tool_results");
                metadata(&mut r, c.agent, "nativeCallId", &json!(call));
                r.as_object_mut().unwrap().remove("callId");
                let raw: Option<String> =
                    s.db.query_row(
                        "SELECT value FROM projected WHERE pos=?1 AND slot=?2",
                        rusqlite::params![previous["pos"].as_u64(), previous["slot"].as_u64()],
                        |r| r.get(0),
                    )
                    .optional()?;
                if let Some(raw) = raw {
                    let mut old: Value = serde_json::from_str(&raw)?;
                    old.as_object_mut().unwrap().remove("callId");
                    metadata(&mut old, c.agent, "nativeCallId", &json!(call));
                    s.db.execute(
                        "UPDATE projected SET value=?1 WHERE pos=?2 AND slot=?3",
                        rusqlite::params![
                            old.to_string(),
                            previous["pos"].as_u64(),
                            previous["slot"].as_u64()
                        ],
                    )?;
                }
                s.save(&key, &json!({"ambiguous":true}))?;
            } else {
                s.save(&key, &json!({"fold":fold,"pos":c.pos,"slot":c.slot}))?;
            }
        } else {
            s.save(&key, &json!({"fold":fold,"pos":c.pos,"slot":c.slot}))?;
        }
    }
    c.emit(s, r, native, fold)
}

pub(crate) fn discover_paths(
    agent: Agent,
    input: &Path,
    out: &Path,
    mut visit: impl FnMut(std::path::PathBuf) -> Result<()>,
) -> Result<()> {
    if input.is_file() {
        visit(input.to_owned())?;
    } else {
        for entry in walkdir::WalkDir::new(input)
            .follow_links(false)
            .max_open(16)
            .sort_by_file_name()
            .into_iter()
            .filter_entry(|e| e.path() != out)
        {
            let entry =
                entry.map_err(|_| Error::Invalid("source directory could not be read".into()))?;
            if !entry.file_type().is_file() {
                continue;
            }
            let path = entry.path();
            let ext = path.extension().and_then(|x| x.to_str()).unwrap_or("");
            let name = entry.file_name().to_string_lossy();
            let jsonl =
                ext == "jsonl" || name.ends_with(".jsonl.zst") || name.ends_with(".jsonl.zstd");
            if matches!(ext, "db" | "sqlite" | "sqlite3" | "vscdb")
                || agent == Agent::OpenClaw && jsonl
            {
                // Native SQLite is authoritative over adjacent migration journals.
                if agent == Agent::OpenClaw
                    && jsonl
                    && path
                        .parent()
                        .and_then(Path::parent)
                        .is_some_and(|p| p.join("agent/openclaw-agent.sqlite").is_file())
                {
                    continue;
                }
                if matches!(ext, "zst" | "zstd") && path.with_extension("").is_file() {
                    continue;
                }
                visit(path.to_owned())?;
            }
        }
    }
    Ok(())
}
