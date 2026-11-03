use crate::{
    spool::{gap, Spool},
    Agent, Result, Summary,
};
use asr_core::{
    identity::derive_id,
    jsonl::{Line, Reader},
};
use serde_json::{json, Value};
use std::{
    fs::File,
    io::{BufRead, BufReader},
    path::{Path, PathBuf},
};

pub fn discover(
    input: &Path,
    out: &Path,
    mut visitor: impl FnMut(PathBuf) -> Result<()>,
) -> Result<()> {
    if input.is_file() {
        return visitor(input.to_owned());
    }
    for entry in walkdir::WalkDir::new(input)
        .follow_links(false)
        .max_open(16)
        .into_iter()
        .filter_entry(|e| e.path() != out)
    {
        let entry = entry
            .map_err(|_| crate::Error::Invalid("source directory could not be read".into()))?;
        if entry.file_type().is_file() || entry.file_type().is_symlink() && entry.path().is_file() {
            let path = entry.path();
            let name = entry.file_name().to_string_lossy();
            if name.ends_with(".jsonl")
                || name.ends_with(".jsonl.zst")
                || name.ends_with(".jsonl.zstd")
            {
                if (name.ends_with(".zst") || name.ends_with(".zstd"))
                    && path.with_extension("").is_file()
                {
                    continue;
                }
                visitor(path.to_owned())?;
            }
        }
    }
    Ok(())
}
pub(crate) fn reader(path: &Path) -> Result<Box<dyn BufRead>> {
    let file = File::open(path)?;
    Ok(
        if path.extension().is_some_and(|e| e == "zst" || e == "zstd") {
            Box::new(BufReader::new(zstd::stream::read::Decoder::new(file)?))
        } else {
            Box::new(BufReader::new(file))
        },
    )
}
fn identity(agent: Agent, value: &Value) -> Option<String> {
    let string = |v: &Value| v.as_str().filter(|s| !s.is_empty()).map(str::to_owned);
    match agent {
        Agent::ClaudeCode => string(&value["agentId"]).or_else(|| string(&value["sessionId"])),
        Agent::Codex if value["type"] == "session_meta" => string(&value["payload"]["id"]),
        _ => None,
    }
}
fn thread_hint(path: &Path) -> Option<String> {
    let name = path.file_name()?.to_str()?;
    if !name.starts_with("rollout-")
        || ![".jsonl", ".jsonl.zst", ".jsonl.zstd"]
            .iter()
            .any(|suffix| name.ends_with(suffix))
    {
        return None;
    }
    static UUID: std::sync::OnceLock<regex::Regex> = std::sync::OnceLock::new();
    UUID.get_or_init(|| {
        regex::Regex::new(r"(?i)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
            .expect("thread identifier pattern")
    })
    .find(name)
    .map(|found| found.as_str().to_owned())
}
fn scan_identity(
    agent: Agent,
    path: &Path,
    input: &mut Reader<Box<dyn BufRead>>,
    mut observe: impl FnMut(&Value) -> Result<()>,
) -> Result<Option<(String, Value)>> {
    let canonical = std::fs::canonicalize(path)?;
    let hint = thread_hint(path).or_else(|| thread_hint(&canonical));
    let mut session = None;
    let mut matching = None;
    let mut ambiguous = false;
    // A native filename can select among recorded thread IDs. It cannot create one.
    while let Some(line) = input.read()? {
        if let Line::Record(value) = line {
            observe(&value)?;
            if agent == Agent::Codex {
                if let Some(id) = identity(agent, &value) {
                    if let Some((previous, _)) = &session {
                        ambiguous |= previous != &id;
                    } else {
                        session = Some((id.clone(), value.clone()));
                    }
                    if matching.is_none() && hint.as_deref() == Some(id.as_str()) {
                        matching = Some((id, value));
                    }
                }
                continue;
            }
            if session.is_none() {
                if let Some(id) = identity(agent, &value) {
                    session = Some((id, value));
                }
            } else if agent == Agent::ClaudeCode {
                if let Some((id, first)) = session.as_mut() {
                    if identity(agent, &value).as_ref() == Some(id) {
                        for field in ["cwd", "version", "agentId", "sessionId", "gitBranch"] {
                            if first.get(field).is_none() {
                                if let Some(v) = value.get(field) {
                                    first[field] = v.clone();
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    if agent == Agent::Codex {
        if matching.is_some() {
            session = matching;
        } else if ambiguous {
            session = None;
        }
    }
    Ok(session)
}

pub fn stage(spool: &mut Spool, agent: Agent, path: &Path, summary: &mut Summary) -> Result<()> {
    if agent.jsonl() {
        return crate::jsonl::source::stage(spool, agent, path, summary);
    }
    let canonical = std::fs::canonicalize(path)?;
    if spool.db.execute(
        "INSERT OR IGNORE INTO sources VALUES(?1)",
        [canonical.to_string_lossy().as_ref()],
    )? == 0
    {
        return Ok(());
    }
    summary.files += 1;
    let mut input = Reader::new(reader(path)?, spool.limit);
    let session = scan_identity(agent, path, &mut input, |value| {
        crate::privacy::questions(spool, value)
    })?;
    let Some((id, first)) = session else {
        summary.source_bytes += input.bytes;
        summary.diagnostic("unidentified_source");
        return Ok(());
    };
    let mut header = crate::common::header(agent, &id);
    let native = if agent == Agent::Codex {
        &first["payload"]
    } else {
        &first
    };
    if let Some(cwd) = native["cwd"]
        .as_str()
        .filter(|p| crate::common::absolute(p))
    {
        header["cwd"] = json!(cwd);
    }
    if let Some(version) = native
        .get(if agent == Agent::Codex {
            "cli_version"
        } else {
            "version"
        })
        .filter(|v| v.is_string())
    {
        header["agent"]["version"] = version.clone();
    }
    crate::repository::capture(&mut header, agent, native);
    if agent == Agent::Codex {
        if let Some(start) = native["timestamp"].as_str() {
            header["startedAt"] = json!(start);
        }
        if let Some(parent) = native
            .pointer("/source/subagent/thread_spawn/parent_thread_id")
            .and_then(Value::as_str)
        {
            header["parent"] = json!({"kind":"subagent","session":asr_core::identity::session_ref(agent.name(),None,parent)});
        } else if let Some(parent) = native["forked_from_id"].as_str() {
            header["parent"] = json!({"kind":"fork","session":asr_core::identity::session_ref(agent.name(),None,parent)});
        }
    } else if let (Some(child), Some(parent)) =
        (first["agentId"].as_str(), first["sessionId"].as_str())
    {
        if child != parent {
            header["parent"] = json!({"kind":"subagent","session":asr_core::identity::session_ref(agent.name(),None,parent)});
        }
    }
    spool.session(&id, &header)?;
    let has_questions: bool =
        spool
            .db
            .query_row("SELECT EXISTS(SELECT 1 FROM secret_questions)", [], |r| {
                r.get(0)
            })?;
    if has_questions {
        let mut answers = Reader::new(reader(path)?, spool.limit);
        while let Some(line) = answers.read()? {
            if let Line::Record(value) = line {
                crate::privacy::answers(spool, &value)?;
            }
        }
    }
    spool.has_secrets = spool
        .db
        .query_row("SELECT EXISTS(SELECT 1 FROM secrets)", [], |r| r.get(0))?;
    let mut input = Reader::new(reader(path)?, spool.limit);
    while let Some(line) = input.read()? {
        match line {
            Line::Record(mut value) => {
                if crate::privacy::sanitize(spool, &mut value)? {
                    value["_asrRedacted"] = json!(true);
                    summary.diagnostic("secret_redacted");
                }
                let native_id = if agent == Agent::ClaudeCode {
                    value["uuid"].as_str().map(|s| format!("uuid:{s}"))
                } else {
                    None
                };
                // Keep each retained revision in source order. Projectors fold by its native identity.
                spool.push(&id, &value, native_id.as_deref())?;
            }
            Line::Malformed | Line::Oversized => {
                let value = gap("unparseable");
                spool.push(
                    &id,
                    &json!({"type":"_gap","record":value}),
                    Some(&derive_id(&[
                        canonical.to_string_lossy().as_ref(),
                        &input.line.to_string(),
                    ])),
                )?;
                summary.diagnostic("unparseable_source_line");
            }
            Line::Incomplete => {
                summary.diagnostic("incomplete_source_tail");
            }
        }
    }
    summary.source_bytes += input.bytes;
    Ok(())
}
