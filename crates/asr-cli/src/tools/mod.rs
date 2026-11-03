pub mod blame;
pub mod redact;
pub mod replay;

use asr_core::{
    identity,
    jsonl::{Line, Reader},
    state::SessionState,
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs,
    io::{BufReader, Read, Write},
    path::Path,
    process::Command,
};

pub type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
pub const META: &str = "org.agentsessionrecord.tools";
pub const LIMIT: usize = 16 * 1024 * 1024;
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

pub fn text<'a>(v: &'a Value, key: &str) -> Option<&'a str> {
    v.get(key)?.as_str()
}
pub fn reference(header: &Value) -> Result<String> {
    Ok(identity::session_ref(
        header["agent"]["name"].as_str().ok_or("missing agent")?,
        text(header, "namespace"),
        text(header, "sessionId").ok_or("missing session identity")?,
    ))
}
pub fn cite(session: &str, r: &Value) -> String {
    format!(
        "{session}#{}",
        identity::encode_component(text(r, "id").unwrap_or("unknown"))
    )
}
pub fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
pub fn producer(source: &str) -> Value {
    json!({"name":"asr-tools","version":VERSION,"method":"converter","source":source})
}

pub struct Stream {
    pub records: Vec<Value>,
    pub warnings: Vec<Value>,
    pub sha256: String,
}
impl Stream {
    pub fn load(path: &Path) -> Result<Self> {
        let mut bytes = Vec::new();
        std::io::Read::take(
            fs::File::open(path).map_err(|_| "ASR input could not be read")?,
            256 * 1024 * 1024 + 1,
        )
        .read_to_end(&mut bytes)?;
        if bytes.len() > 256 * 1024 * 1024 {
            return Err("ASR input exceeds 256 MiB limit".into());
        }
        let mut reader = Reader::new(BufReader::new(bytes.as_slice()), LIMIT);
        let mut records = Vec::new();
        let mut warnings = Vec::new();
        while let Some(line) = reader.read()? {
            match line {
                Line::Record(value) => records.push(value),
                Line::Incomplete => {
                    warnings.push(json!({"code":"incomplete-tail","line":reader.line}))
                }
                _ => {
                    warnings.push(json!({"code":"malformed-line","line":reader.line}));
                    records.push(json!({"type":"gap","id":format!("asr-recovery-{}",reader.line),"reason":"unparseable","count":1}));
                }
            }
        }
        if records
            .first()
            .is_none_or(|h| h["type"] != "session" || h["formatVersion"] != "0.1")
        {
            return Err("ASR requires a first-line 0.1 session header".into());
        }
        reference(&records[0])?;
        let mut ids = std::collections::BTreeSet::new();
        for (i, r) in records.iter().enumerate() {
            let id = text(r, "id")
                .filter(|id| identity::valid_id(id))
                .ok_or("invalid record identity")?;
            if !ids.insert(id) || (i > 0 && r["type"] == "session") {
                return Err("duplicate record or session identity".into());
            }
        }
        if let Some(boundary) = records[0]["parent"]["copiedThrough"].as_str() {
            if !records
                .iter()
                .skip(1)
                .any(|r| text(r, "id") == Some(boundary))
            {
                return Err("unresolved copiedThrough boundary".into());
            }
        }
        Ok(Self {
            records,
            warnings,
            sha256: digest(&bytes),
        })
    }
    pub fn session(&self) -> String {
        reference(&self.records[0]).expect("checked header")
    }
    pub fn copied(&self, index: usize) -> bool {
        let end = self.records[0]["parent"]["copiedThrough"]
            .as_str()
            .and_then(|id| self.records.iter().position(|r| text(r, "id") == Some(id)))
            .unwrap_or(0);
        self.records[index].get("copiedFrom").is_some() || (index > 0 && index <= end)
    }
    pub fn unique_call(&self, call: &str) -> Option<&Value> {
        let mut calls = self
            .records
            .iter()
            .filter(|r| r["type"] == "tool_call" && text(r, "callId") == Some(call));
        let first = calls.next()?;
        calls.next().is_none().then_some(first)
    }
    pub fn result(&self, call: &str) -> Option<&Value> {
        self.unique_call(call)?;
        let mut results = self
            .records
            .iter()
            .filter(|r| r["type"] == "tool_result" && text(r, "callId") == Some(call));
        let first = results.next()?;
        results.next().is_none().then_some(first)
    }
    pub fn state(&self) -> SessionState {
        let mut state = SessionState::default();
        for r in &self.records {
            state.apply(r);
        }
        state
    }
    pub fn diagnostics(&self) -> Value {
        let mut unresolved = Vec::new();
        if let Some(parent) = self.records[0].get("parent") {
            unresolved.push(json!({"kind":"parent","reference":parent["session"]}));
        }
        for r in &self.records {
            if r["type"] == "tool_call"
                && text(r, "callId").is_some_and(|id| self.result(id).is_none())
            {
                unresolved.push(json!({"record":r["id"],"kind":"outcome"}));
            }
            if r.get("copiedFrom").is_some() && r["copiedFrom"].get("session").is_none() {
                unresolved.push(json!({"record":r["id"],"kind":"copy","sourceRecord":r["copiedFrom"]["record"]}));
            }
            for (field, kind) in [("inferenceId", "inference"), ("callId", "call")] {
                if let Some(id) = text(r, field) {
                    let found = if kind == "call" {
                        self.unique_call(id).is_some()
                    } else {
                        self.records
                            .iter()
                            .filter(|v| v["type"] == "inference" && text(v, "id") == Some(id))
                            .count()
                            == 1
                    };
                    if !found {
                        unresolved.push(json!({"record":r["id"],"kind":kind,"id":id}));
                    }
                }
            }
            for (kind, value) in [
                ("copy", r["copiedFrom"]["session"].clone()),
                ("subagent", r["subagent"]["session"].clone()),
                ("sender", r["from"].clone()),
            ] {
                if !value.is_null() {
                    unresolved.push(json!({"record":r["id"],"kind":kind,"reference":value}));
                }
            }
        }
        json!({"session":self.session(),"missing":self.state().missing,"gaps":self.records.iter().filter(|r|r["type"]=="gap").map(|r|json!({"id":r["id"],"reason":r["reason"],"count":r["count"]})).collect::<Vec<_>>(),"warnings":self.warnings,"unresolved":unresolved})
    }
}

/// Validate a private candidate before publishing it at a new destination.
pub fn write_session(out: &Path, records: &[Value]) -> Result<Value> {
    if out.exists() {
        return Err("output already exists".into());
    }
    let parent = out
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    let mut temp = tempfile::Builder::new()
        .prefix(".asr-tools-")
        .suffix(".jsonl")
        .tempfile_in(parent)?;
    for r in records {
        serde_json::to_writer(&mut temp, r)?;
        temp.write_all(b"\n")?;
    }
    temp.flush()?;
    let validator = crate::validator().ok_or("Node validator not found")?;
    let validation = Command::new("node")
        .arg(validator)
        .arg("--json")
        .arg(temp.path())
        .output()?;
    if !validation.status.success() {
        return Err("output failed ASR validation, no file was created".into());
    }
    // Validator output is not echoed because it can contain input values.
    let report: Value = serde_json::from_slice(&validation.stdout).unwrap_or(json!({}));
    temp.persist_noclobber(out)
        .map_err(|_| "output could not be created without overwriting")?;
    Ok(json!({"records":records.len(),"validated":true,"validation":validation_counts(&report)}))
}
fn validation_counts(v: &Value) -> BTreeMap<String, usize> {
    let mut counts = BTreeMap::new();
    fn visit(v: &Value, counts: &mut BTreeMap<String, usize>) {
        match v {
            Value::Object(o) => {
                if let Some(Value::String(code)) = o.get("code") {
                    *counts.entry(code.clone()).or_default() += 1;
                }
                for child in o.values() {
                    visit(child, counts);
                }
            }
            Value::Array(a) => {
                for child in a {
                    visit(child, counts);
                }
            }
            _ => {}
        }
    }
    visit(v, &mut counts);
    counts
}

/// Join available session files without assigning credit from relationship links.
pub fn relationships(streams: &[Stream]) -> Value {
    let available = streams
        .iter()
        .map(Stream::session)
        .collect::<std::collections::BTreeSet<_>>();
    let mut links = BTreeMap::<(String, String), Value>::new();
    for stream in streams {
        let session = stream.session();
        if let Some(parent) = stream.records[0].get("parent") {
            if let Some(source) = text(parent, "session") {
                let link = links.entry((source.to_owned(), session.clone())).or_insert_with(|| json!({"parent":source,"child":session,"childAvailable":true,"parentAvailable":available.contains(source)}));
                link["kind"] = parent["kind"].clone();
                if let Some(call) = parent.get("callId") {
                    link["callId"] = call.clone();
                }
            }
        }
        for record in &stream.records {
            if !matches!(text(record, "type"), Some("tool_call" | "tool_result")) {
                continue;
            }
            if let Some(child) = text(&record["subagent"], "session") {
                let link=links.entry((session.clone(), child.to_owned())).or_insert_with(|| json!({"parent":session,"child":child,"kind":"subagent","parentAvailable":true,"childAvailable":available.contains(child)}));
                if let Some(call) = record.get("callId") {
                    link["callId"] = call.clone();
                }
            }
        }
    }
    json!(links.into_values().collect::<Vec<_>>())
}

pub fn resolved_diagnostics(
    stream: &Stream,
    available: &std::collections::BTreeSet<String>,
) -> Value {
    let mut value = stream.diagnostics();
    value["unresolved"].as_array_mut().unwrap().retain(|item| {
        let Some(reference) = text(item, "reference") else {
            return true;
        };
        let session = reference.split('#').next().unwrap_or(reference);
        !available.contains(session)
    });
    value
}
