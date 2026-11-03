use crate::{
    spool::{DiskIds, Spool},
    Agent, Result, Summary,
};
use asr_core::identity::{derive_id, valid_id};
use serde_json::{json, Value};
use std::{
    collections::BTreeSet,
    fs::{self, DirBuilder},
    io::BufWriter,
    path::Path,
};

pub(crate) fn destination(path: &Path) -> Result<std::path::PathBuf> {
    let absolute = if path.is_absolute() {
        path.to_owned()
    } else {
        std::env::current_dir()?.join(path)
    };
    let mut normalized = std::path::PathBuf::new();
    for part in absolute.components() {
        match part {
            std::path::Component::ParentDir => {
                normalized.pop();
            }
            std::path::Component::CurDir => {}
            other => normalized.push(other.as_os_str()),
        }
        if normalized.exists() {
            normalized = fs::canonicalize(&normalized)?;
        }
    }
    Ok(normalized)
}

pub(crate) fn private_dir(path: &Path) -> Result<()> {
    let mut builder = DirBuilder::new();
    builder.recursive(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    builder.create(path)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o700))?;
    }
    Ok(())
}
pub fn absolute(path: &str) -> bool {
    path.starts_with('/') || path.starts_with("\\\\") || path.as_bytes().get(1) == Some(&b':')
}
pub fn path(path: &str, cwd: Option<&str>) -> String {
    if absolute(path) {
        path.into()
    } else {
        match cwd {
            Some(cwd) => format!("{}/{}", cwd.trim_end_matches('/'), path.replace('\\', "/")),
            None => path.replace('\\', "/"),
        }
    }
}
pub(crate) struct Context {
    pub agent: Agent,
    pub session: String,
    pub pos: u64,
    pub slot: u64,
    pub ordinal: u64,
    pub source: Value,
    pub turn: Option<String>,
    pub redacted: bool,
    pub missing: BTreeSet<String>,
    pub settings: Value,
    pub cwd: Option<String>,
    pub namespace: Option<String>,
}
impl Context {
    pub fn new(agent: Agent, session: String) -> Self {
        Self {
            agent,
            session,
            pos: 0,
            slot: 0,
            ordinal: 0,
            source: Value::Null,
            turn: None,
            redacted: false,
            missing: BTreeSet::new(),
            settings: json!({}),
            cwd: None,
            namespace: None,
        }
    }
    pub fn loss(&mut self, key: &str) {
        self.missing.insert(key.into());
    }
    pub fn position(&mut self, pos: u64, source: &Value) {
        self.pos = pos;
        self.slot = 0;
        self.ordinal += 1;
        self.source = json!({});
        self.redacted = source["_asrRedacted"] == true;
        if let Some(ts) = source["timestamp"].as_str() {
            self.source["ts"] = json!(ts);
        }
        if let Some(turn) = source["promptId"]
            .as_str()
            .or_else(|| source["payload"]["turn_id"].as_str())
            .or_else(|| {
                source
                    .pointer("/payload/internal_chat_message_metadata_passthrough/turn_id")
                    .and_then(Value::as_str)
            })
        {
            self.turn = Some(turn.into());
        }
        if let Some(turn) = &self.turn {
            self.source["turnId"] = json!(turn);
        }
    }
    pub fn emit(
        &mut self,
        s: &Spool,
        mut value: Value,
        native: Option<&str>,
        fold: Option<&str>,
    ) -> Result<()> {
        normalize_reasoning(&mut value);
        let slot = self.slot;
        self.slot += 1;
        for (key, v) in self.source.as_object().into_iter().flatten() {
            if value.get(key).is_none() {
                value[key] = v.clone();
            }
        }
        let derived = derive_id(&[
            &self.session,
            fold.unwrap_or(&format!("{}:{slot}", self.ordinal)),
            value["type"].as_str().unwrap_or("record"),
        ]);
        value["id"] = json!(native.filter(|v| valid_id(v)).unwrap_or(&derived));
        if self.redacted {
            value["truncated"] = json!(true);
            self.loss("redacted_content");
        }
        crate::privacy::scrub_opaque(&mut value, true);
        if clean_media(&mut value) {
            value["truncated"] = json!(true);
            self.loss("content.binary");
        }
        if value.to_string().len() > s.limit {
            self.loss("record_size_limit");
            value = json!({"type":"gap","id":derived,"reason":"not_retained","count":1,"detail":"A converted record exceeded the configured size limit."});
        }
        s.emit(self.pos, slot, value, fold)
    }
    pub fn vendor(&mut self, s: &Spool, value: &Value) -> Result<()> {
        self.emit(s,json!({"type":format!("{}/event",self.agent.domain()),"_meta":{self.agent.domain():{"native":value}}}),None,None)
    }
    pub fn info(&mut self, s: &Spool, value: Value) -> Result<()> {
        self.emit(s, value, None, None)
    }
    pub fn result(&mut self, s: &Spool, value: Value) -> Result<()> {
        let key = value["callId"].as_str().map(|id| format!("result:{id}"));
        // SQLite's previous substr lookup could not match a NUL-containing prefix.
        if let Some(call) = value["callId"].as_str().filter(|id| !id.contains('\0')) {
            let prefix = format!("approval:{call}:");
            // The final ASCII colon has a successor, so this range covers
            // exactly the prefix under SQLite's binary text ordering.
            let end = format!("approval:{call};");
            let mut cursor = String::new();
            loop {
                use rusqlite::OptionalExtension;
                let start = prefix.as_str().max(cursor.as_str());
                let row: Option<(String, String, u64)> =
                    s.db.prepare_cached(crate::spool::APPROVAL_LOOKUP)?
                        .query_row(rusqlite::params![start, end, cursor], |r| {
                            Ok((r.get(0)?, r.get(1)?, r.get(2)?))
                        })
                        .optional()?;
                let Some((fold, raw, old_pos)) = row else {
                    break;
                };
                cursor = fold.clone();
                if old_pos != self.pos {
                    s.db.prepare_cached("DELETE FROM projected WHERE fold=?1")?
                        .execute([&fold])?;
                    s.emit(
                        self.pos,
                        self.slot,
                        serde_json::from_str(&raw)?,
                        Some(&fold),
                    )?;
                    self.slot += 1;
                }
            }
        }
        let native = value["id"].as_str().map(str::to_owned);
        self.emit(s, value, native.as_deref(), key.as_deref())
    }
    pub fn settings(&mut self, s: &Spool, settings: Value) -> Result<()> {
        if settings.as_object().is_some_and(|o| !o.is_empty()) {
            self.info(s, json!({"type":"session_info","agentSettings":settings}))?;
        }
        Ok(())
    }
}
fn clean_media(value: &mut Value) -> bool {
    let mut changed = false;
    match value {
        Value::Object(o) => {
            if matches!(
                o.get("type").and_then(Value::as_str),
                Some("image" | "audio")
            ) && o
                .get("data")
                .is_some_and(|v| v.as_str().is_none_or(|s| !base64(s)))
            {
                o.remove("data");
                changed = true;
            }
            for v in o.values_mut() {
                changed |= clean_media(v);
            }
        }
        Value::Array(a) => {
            for v in a {
                changed |= clean_media(v);
            }
        }
        _ => {}
    }
    changed
}
fn base64(s: &str) -> bool {
    if s.len() % 4 != 0 {
        return false;
    }
    let end = s.trim_end_matches('=').len();
    if s.len() - end > 2 {
        return false;
    }
    s.as_bytes()[..end]
        .iter()
        .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'+' | b'/'))
}

pub fn copy(dest: &mut Value, to: &str, source: &Value, from: &str) {
    if let Some(value) = source.get(from).filter(|v| !v.is_null()) {
        dest[to] = value.clone();
    }
}
pub fn text(value: &str) -> Value {
    json!({"type":"text","text":value})
}
/// Visibility describes the saved representation, never the model's hidden state.
pub fn reasoning(text: Option<&str>, visibility: Option<&str>) -> Value {
    match (text.filter(|t| !t.is_empty()), visibility) {
        (_, Some("encrypted")) => json!({"type":"reasoning","visibility":"encrypted"}),
        (None, _) | (_, Some("omitted")) => json!({"type":"reasoning","visibility":"omitted"}),
        (Some(text), Some("summary")) => {
            json!({"type":"reasoning","visibility":"summary","summary":[text]})
        }
        (Some(text), Some(visibility)) => {
            json!({"type":"reasoning","visibility":visibility,"text":text})
        }
        (Some(text), None) => json!({"type":"reasoning","text":text}),
    }
}
fn normalize_reasoning(record: &mut Value) {
    for part in record
        .get_mut("content")
        .and_then(Value::as_array_mut)
        .into_iter()
        .flatten()
    {
        if part["type"] != "reasoning" {
            continue;
        }
        let object = part.as_object_mut().unwrap();
        if matches!(
            object.get("visibility").and_then(Value::as_str),
            Some("encrypted" | "omitted")
        ) {
            object.remove("text");
            object.remove("summary");
        } else if object
            .get("text")
            .and_then(Value::as_str)
            .is_none_or(str::is_empty)
            && object
                .get("summary")
                .and_then(Value::as_array)
                .is_none_or(|a| a.iter().all(|t| t.as_str().is_none_or(str::is_empty)))
        {
            object.remove("text");
            object.remove("summary");
            object.insert("visibility".into(), json!("omitted"));
        } else if object.get("summary").is_some() {
            object.insert("visibility".into(), json!("summary"));
        }
    }
}
pub fn vendor_part(agent: Agent, native: &Value) -> Value {
    json!({"type":format!("{}/content",agent.domain()),"_meta":{agent.domain():{"native":native}}})
}
pub fn parts(value: &Value, agent: Agent) -> Vec<Value> {
    if let Some(s) = value.as_str() {
        return vec![text(s)];
    }
    let mut out = Vec::new();
    for part in value.as_array().into_iter().flatten() {
        let p = match part["type"].as_str() {
            Some("text" | "input_text" | "output_text" | "Text") => part["text"].as_str().map(text),
            Some("thinking") => Some(reasoning(
                part["thinking"].as_str(),
                (agent == Agent::ClaudeCode).then_some("summary"),
            )),
            Some("redacted_thinking") => Some(json!({"type":"reasoning","visibility":"encrypted"})),
            Some("reasoning") => Some(part.clone()),
            Some("image") if part["source"]["type"] == "base64" => Some(
                json!({"type":"image","mimeType":part["source"]["media_type"].as_str().unwrap_or("application/octet-stream"),"data":part["source"]["data"]}),
            ),
            Some("image" | "audio") if part["mimeType"].is_string() => Some(part.clone()),
            Some("resource_link" | "resource") => Some(part.clone()),
            Some("tool_use" | "tool_result") => None,
            Some(_) => Some(vendor_part(agent, part)),
            None => None,
        };
        if let Some(mut p) = p {
            for key in ["author", "origin"] {
                if let Some(v) = part.get(key) {
                    p[key] = v.clone();
                }
            }
            if p["type"] == "reasoning" && p["visibility"] == "encrypted" {
                p.as_object_mut().unwrap().remove("text");
                p.as_object_mut().unwrap().remove("summary");
            }
            out.push(p);
        }
    }
    out
}
pub fn kind(name: &str) -> Option<&'static str> {
    match name {
        "Read" | "read_file" => Some("read"),
        "Write" | "Edit" | "MultiEdit" | "apply_patch" => Some("edit"),
        "Bash" | "exec" | "exec_command" | "shell" | "shell_command" | "local_shell" => {
            Some("execute")
        }
        "Grep" | "Glob" | "WebSearch" | "search" => Some("search"),
        "WebFetch" => Some("fetch"),
        "EnterPlanMode" | "ExitPlanMode" => Some("switch_mode"),
        _ => None,
    }
}
pub fn call(
    s: &Spool,
    c: &mut Context,
    native: &Value,
    id: &str,
    name: Option<&str>,
    input: Option<(&str, Value)>,
) -> Result<()> {
    let mut r = json!({"type":"tool_call","callId":id,"requestedBy":"model"});
    if let Some(name) = name {
        r["name"] = json!(name);
        let kind = if c.agent == Agent::ClaudeCode {
            Some(match name {
                "Edit" | "MultiEdit" | "Write" | "NotebookEdit" => "edit",
                "Read" => "read",
                "Bash" | "PowerShell" => "execute",
                "Glob" | "Grep" | "ToolSearch" => "search",
                "WebFetch" | "WebSearch" => "fetch",
                "TodoWrite" => "think",
                "EnterPlanMode" | "ExitPlanMode" => "switch_mode",
                _ => "other",
            })
        } else if c.agent == Agent::Codex {
            match name {
                "update_plan" => Some("think"),
                "request_user_input" => Some("other"),
                _ => kind(name),
            }
        } else {
            kind(name)
        };
        if let Some(kind) = kind {
            r["kind"] = json!(kind);
        }
    }
    if let Some((field, value)) = input {
        r[field] = value;
    }
    if let Some(file) = r["input"]["file_path"]
        .as_str()
        .or_else(|| r["input"]["path"].as_str())
    {
        r["locations"] = json!([{"path":path(file,c.cwd.as_deref())}]);
    }
    if c.agent == Agent::ClaudeCode {
        if let Some(inference) = native["message"]["id"].as_str() {
            r["inferenceId"] = json!(inference);
        }
    } else if c.agent == Agent::Codex {
        if let Some(inference) = native["response_id"].as_str() {
            r["inferenceId"] = json!(inference);
        }
    }
    if let Some(previous) = s.entity(&format!("call:{id}"))? {
        if previous != r {
            c.loss("call_revisions");
        }
    }
    s.save(&format!("call:{id}"), &r)?;
    let record = native["id"]
        .as_str()
        .or_else(|| (c.agent == Agent::ClaudeCode).then_some(id));
    let fold = if c.agent == Agent::ClaudeCode {
        native["message"]["id"]
            .as_str()
            .map(|response| format!("call-record:{response}:{id}"))
    } else {
        record.map(|id| format!("call-record:{id}"))
    };
    c.emit(s, r, record, fold.as_deref())
}

pub fn finish(
    s: &Spool,
    c: &mut Context,
    mut header: Value,
    out: &Path,
    summary: &mut Summary,
) -> Result<()> {
    static SCHEMA: std::sync::OnceLock<jsonschema::Validator> = std::sync::OnceLock::new();
    let schema = SCHEMA.get_or_init(|| {
        let schema: Value =
            serde_json::from_str(include_str!("../../../schema/v0/agent-session.schema.json"))
                .expect("embedded ASR schema");
        jsonschema::options()
            .with_draft(jsonschema::Draft::Draft202012)
            .should_validate_formats(true)
            .build(&schema)
            .expect("embedded ASR schema compiles")
    });
    let reference = asr_core::identity::session_ref(
        c.agent.name(),
        header["namespace"].as_str(),
        header["sessionId"].as_str().unwrap_or(&c.session),
    );
    // Validate before writing the header so every rejected projection declares its loss.
    s.for_each_record(|pos, slot, value| {
        let normalized = output_record(s, &c.session, value.clone(), pos, slot)?;
        if !schema.is_valid(&normalized) || asr_core::Record::from_value(normalized).is_err() {
            c.loss("record_shape");
            summary.diagnostic_for(&reference, "record_shape");
            let gap = json!({"type":"gap","id":value["id"],"reason":"unparseable","detail":"A converted record did not match the format."});
            s.db.execute("UPDATE projected SET value=?1 WHERE pos=?2 AND slot=?3", rusqlite::params![gap.to_string(),pos,slot])?;
        }
        Ok(())
    })?;
    if let Some(losses) = header["missing"].as_array() {
        c.missing
            .extend(losses.iter().filter_map(Value::as_str).map(str::to_owned));
    }
    header["missing"] = json!(c.missing);
    header["extensions"] = json!([c.agent.domain()]);
    if header.get("cwd").is_none() {
        if let Some(cwd) = &c.cwd {
            header["cwd"] = json!(cwd);
        }
    }
    if !schema.is_valid(&header) {
        return Err(crate::Error::Session {
            session: reference,
            code: "session_header_shape",
        });
    }
    let basename = format!("{}-{}.jsonl", c.agent.name(), derive_id(&[&c.session]));
    let mut file = tempfile::NamedTempFile::new_in(out)?;
    let mut writer =
        asr_core::Writer::with_store(BufWriter::new(file.as_file_mut()), &header, DiskIds(s))?;
    s.for_each_record(|pos, slot, value| {
        let value = output_record(s, &c.session, value, pos, slot)?;
        writer.append(&value)?;
        Ok(())
    })?;
    let records = writer.records;
    writer.flush()?;
    drop(writer);
    file.as_file().sync_all()?;
    file.persist(out.join(basename)).map_err(|e| e.error)?;
    summary.records += records;
    summary.sessions += 1;
    Ok(())
}

fn output_record(s: &Spool, session: &str, mut value: Value, pos: u64, slot: u64) -> Result<Value> {
    value["id"] = json!(output_id(s, session, &value, pos, slot)?);
    if let Some(reference) = value["inferenceId"].as_str() {
        use rusqlite::OptionalExtension;
        let target: Option<(u64, u64, String)> =
            s.db.prepare_cached("SELECT pos,slot,value FROM projected WHERE fold=?1")?
                .query_row([format!("inference:{reference}")], |r| {
                    Ok((r.get(0)?, r.get(1)?, r.get(2)?))
                })
                .optional()?;
        if let Some((target_pos, target_slot, raw)) = target {
            value["inferenceId"] = json!(output_id(
                s,
                session,
                &serde_json::from_str(&raw)?,
                target_pos,
                target_slot,
            )?);
        }
    }
    Ok(value)
}

fn output_id(s: &Spool, session: &str, value: &Value, pos: u64, slot: u64) -> Result<String> {
    // Use a native ID only when unique across all projected records.
    let id = value["id"].as_str().unwrap_or_default();
    let count: u64 =
        s.db.prepare_cached("SELECT count(*) FROM projected WHERE json_extract(value,'$.id')=?1")?
            .query_row([id], |r| r.get(0))?;
    Ok(if count > 1 || id == "header" {
        derive_id(&[session, id, &pos.to_string(), &slot.to_string()])
    } else {
        id.to_owned()
    })
}

/// Keep native counters only when ASR can represent their integer value exactly.
pub fn count(v: &Value) -> Option<u64> {
    v.as_u64().filter(|n| *n <= 9_007_199_254_740_991)
}
pub fn nonempty(v: &Value) -> Option<&str> {
    v.as_str().filter(|s| !s.is_empty())
}
/// These source profiles record numeric timestamps as epoch milliseconds.
pub fn timestamp_millis(v: &Value) -> Option<String> {
    if let Some(s) = v.as_str() {
        return chrono::DateTime::parse_from_rfc3339(s)
            .ok()
            .map(|_| s.to_owned());
    }
    chrono::DateTime::from_timestamp_millis(v.as_i64()?)
        .map(|v| v.to_rfc3339_opts(chrono::SecondsFormat::Millis, true))
}

/// Start a converter stream with the losses shared by native source profiles.
pub fn header(agent: Agent, id: &str) -> Value {
    json!({"type":"session","id":"header","formatVersion":"0.1","agent":{"name":agent.name()},"sessionId":id,"producer":{"name":"asr","version":env!("CARGO_PKG_VERSION"),"method":"converter","source":agent.source()},"missing":["approvals","copies","commits","file_changes","subagents","tools","agent_settings","model","usage","timestamps","cost"]})
}
