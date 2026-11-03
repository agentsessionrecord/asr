//! Agent-owned identity and storage selection. Native directory IDs are used only for documented layouts.
use super::helpers::{self, string};
use crate::{
    common, privacy,
    source::reader,
    spool::{gap, Spool},
    Agent, Result, Summary,
};
use asr_core::{
    identity::session_ref,
    jsonl::{Line, Reader},
};
use serde_json::{json, Value};
use std::{io::Read, path::Path};

pub fn selected(agent: Agent, path: &Path) -> Result<bool> {
    let name = path.file_name().and_then(|s| s.to_str()).unwrap_or("");
    Ok(match agent {
        Agent::KimiCode => name == "wire.jsonl",
        Agent::Junie => name == "events.jsonl",
        Agent::Antigravity => {
            name == "transcript_full.jsonl"
                || name == "transcript.jsonl"
                    && !path.with_file_name("transcript_full.jsonl").is_file()
        }
        Agent::DeepSeekHarness => {
            fn generation(n: &str) -> Option<u64> {
                let n = n
                    .strip_suffix(".zstd")
                    .or_else(|| n.strip_suffix(".zst"))
                    .unwrap_or(n);
                if n == "session.jsonl" {
                    return Some(0);
                }
                let n = n.strip_prefix("session.v")?.strip_suffix(".jsonl")?;
                let v: u64 = n.parse().ok()?;
                (v > 0 && v.to_string() == n).then_some(v)
            }
            if let (Some(current), Some(parent)) = (generation(name), path.parent()) {
                let mut newest = true;
                for e in std::fs::read_dir(parent)? {
                    let e = e?;
                    if e.file_type()?.is_file()
                        && e.file_name()
                            .to_str()
                            .and_then(generation)
                            .is_some_and(|n| n > current)
                    {
                        newest = false;
                    }
                }
                newest
            } else {
                true
            }
        }
        _ => true,
    })
}
fn identity(agent: Agent, v: &Value) -> Option<&str> {
    match agent {
        Agent::CopilotCli if v["type"] == "session.start" => string(&v["data"]["sessionId"]),
        Agent::Droid if v["type"] == "session_start" => {
            string(&v["sessionId"]).or_else(|| string(&v["id"]))
        }
        Agent::Qoder => string(&v["sessionId"]),
        Agent::QwenCode => {
            if v["isSidechain"] == true {
                string(&v["agentId"])
            } else {
                string(&v["sessionId"])
            }
        }
        Agent::GrokBuild => v
            .pointer("/params/sessionId")
            .or_else(|| v.get("sessionId"))
            .and_then(string),
        Agent::Pi
            if v["kind"] == "header" && v["version"] == 4
                || v["type"] == "session" && v["version"].as_u64().is_some_and(|v| v <= 3) =>
        {
            string(&v["id"])
        }
        Agent::DeepSeekHarness
            if v["type"] == "session" && matches!(v["version"].as_u64(), Some(0 | 4)) =>
        {
            string(&v["id"])
        }
        Agent::OpenClaw if v["type"] == "session" => string(&v["id"]),
        Agent::Tabnine => string(&v["sessionId"]),
        _ => None,
    }
}
fn document(path: &Path, limit: usize) -> Result<Value> {
    if !path.is_file() {
        return Ok(json!({}));
    }
    let mut data = Vec::new();
    std::fs::File::open(path)?
        .take(limit as u64 + 1)
        .read_to_end(&mut data)?;
    if data.len() > limit {
        return Ok(json!({"_asrSidecarLoss":true}));
    }
    Ok(std::str::from_utf8(&data)
        .ok()
        .and_then(|s| asr_core::jsonl::decode(s).ok())
        .unwrap_or(json!({"_asrSidecarLoss":true})))
}
fn header(agent: Agent, id: &str, n: &Value) -> Value {
    let mut h = common::header(agent, id);
    h["missing"].as_array_mut().unwrap().extend(
        [
            "inference_settings",
            "reasoning",
            "content.binary",
            "message.author",
        ]
        .map(|loss| json!(loss)),
    );
    let n = if agent == Agent::CopilotCli {
        &n["data"]
    } else {
        n
    };
    if let Some(cwd) = n["cwd"]
        .as_str()
        .or_else(|| n.pointer("/context/cwd").and_then(Value::as_str))
        .filter(|p| common::absolute(p))
    {
        h["cwd"] = json!(cwd);
    }
    crate::repository::capture(&mut h, agent, n);
    let version = if agent == Agent::CopilotCli {
        &n["copilotVersion"]
    } else {
        &n["version"]
    };
    if version.is_string() {
        h["agent"]["version"] = version.clone();
    }
    let start = n.get("startTime").and_then(helpers::time).or_else(|| {
        let header = matches!(
            n["type"].as_str(),
            Some("session" | "session_start" | "session_meta")
        ) || n["kind"] == "header";
        header
            .then(|| {
                n.get("createdAt")
                    .or_else(|| n.get("timestamp"))
                    .and_then(helpers::time)
            })
            .flatten()
    });
    if let Some(start) = start {
        h["startedAt"] = json!(start);
    }
    let parent = match agent {
        Agent::Droid => string(&n["callingSessionId"]).map(|p| (p, "subagent")),
        Agent::QwenCode if n["isSidechain"] == true => {
            string(&n["sessionId"]).map(|p| (p, "subagent"))
        }
        Agent::QwenCode => n
            .pointer("/forkedFrom/sessionId")
            .and_then(string)
            .map(|p| (p, "fork")),
        Agent::DeepSeekHarness => string(&n["parentSession"]).map(|p| {
            (
                p,
                if n["origin"] == "subagent" {
                    "subagent"
                } else {
                    "fork"
                },
            )
        }),
        Agent::Pi => string(&n["parentSessionId"])
            .or_else(|| {
                string(&n["parentSession"]).filter(|p| !p.contains('/') && !p.contains('\\'))
            })
            .map(|p| (p, "fork")),
        _ => None,
    };
    if let Some((p, kind)) = parent {
        h["parent"] = json!({"kind":kind,"session":session_ref(agent.name(),None,p)});
    }
    h
}
pub fn stage(s: &mut Spool, agent: Agent, path: &Path, summary: &mut Summary) -> Result<()> {
    if !selected(agent, path)? {
        return Ok(());
    }
    let canonical = std::fs::canonicalize(path)?;
    if s.db.execute(
        "INSERT OR IGNORE INTO sources VALUES(?1)",
        [canonical.to_string_lossy().as_ref()],
    )? == 0
    {
        return Ok(());
    }
    summary.files += 1;
    let mut first = None;
    let mut lines = Reader::new(reader(path)?, s.limit);
    while let Some(line) = lines.read()? {
        if let Line::Record(v) = line {
            privacy::questions(s, &v)?;
            if first.is_none() {
                if let Some(id) = identity(agent, &v) {
                    first = Some((id.to_owned(), v));
                } else if matches!(agent, Agent::KimiCode | Agent::Junie | Agent::Antigravity) {
                    first = Some((String::new(), v));
                }
            }
        }
    }
    let mut native = first.as_ref().map(|(_, v)| v.clone()).unwrap_or(json!({}));
    let mut id = first.map(|(id, _)| id);
    let mut namespace = None;
    if agent == Agent::KimiCode {
        if native["type"] != "metadata" || native["protocol_version"] != "1.5" {
            return Err(crate::Error::Invalid(
                "unsupported Kimi wire protocol, expected 1.5".into(),
            ));
        }
        id = None;
        if let Some(dir) = path
            .parent()
            .filter(|p| p.parent().is_some_and(|p| p.ends_with("agents")))
        {
            if let (Some(a), Some(session)) = (
                dir.file_name().and_then(|s| s.to_str()),
                dir.parent().and_then(Path::parent),
            ) {
                let state_path = if session.join("state.json").is_file() {
                    session.join("state.json")
                } else {
                    session.join("session-meta/state.json")
                };
                let state = document(&state_path, s.limit)?;
                if let Some(session_id) = string(&state["id"]) {
                    id = Some(if a == "main" {
                        session_id.to_owned()
                    } else {
                        a.to_owned()
                    });
                    namespace = (a != "main").then(|| session_id.to_owned());
                }
                native["_agentId"] = json!(a);
                native["_state"] = state;
            }
        }
        if id.as_deref().is_none_or(str::is_empty) {
            return Err(crate::Error::Invalid(
                "Kimi export requires state.json with a native session ID".into(),
            ));
        }
    } else if agent == Agent::Junie {
        id = path
            .parent()
            .and_then(Path::file_name)
            .and_then(|s| s.to_str())
            .filter(|s| s.starts_with("session-"))
            .map(str::to_owned);
    } else if agent == Agent::Antigravity {
        id = path
            .parent()
            .filter(|p| p.ends_with("logs"))
            .and_then(Path::parent)
            .filter(|p| p.ends_with(".system_generated"))
            .and_then(Path::parent)
            .and_then(Path::file_name)
            .and_then(|s| s.to_str())
            .map(str::to_owned);
    }
    let Some(id) = id.filter(|id| !id.is_empty()) else {
        summary.source_bytes += lines.bytes;
        summary.diagnostic("unidentified_source");
        return Ok(());
    };
    let key = namespace
        .as_ref()
        .map(|n| json!([n, id]).to_string())
        .unwrap_or(id.clone());
    let mut h = header(agent, &id, &native);
    if let Some(ns) = &namespace {
        h["namespace"] = json!(ns);
    }
    if agent == Agent::KimiCode {
        let state = &native["_state"];
        if let Some(cwd) = state["workDir"]
            .as_str()
            .or_else(|| state["cwd"].as_str())
            .filter(|p| common::absolute(p))
        {
            h["cwd"] = json!(cwd);
        }
        crate::repository::capture(&mut h, agent, state);
        let agent_id = native["_agentId"].as_str().unwrap_or("main");
        if let Some(parent) = state["agents"][agent_id]["labels"]["parentAgentId"]
            .as_str()
            .or_else(|| state["agents"][agent_id]["parentAgentId"].as_str())
        {
            let session_id = state["id"].as_str().expect("native session ID");
            h["parent"] = json!({"kind":"subagent","session": if parent == "main" { session_ref(agent.name(),None,session_id) } else { session_ref(agent.name(),Some(session_id),parent) }});
        } else if agent_id == "main" {
            if let Some(parent) = state["forkedFrom"].as_str() {
                h["parent"] =
                    json!({"kind":"fork","session":session_ref(agent.name(),None,parent)});
            }
        }
        if let Some(fork) = state["agents"][agent_id]["forkedFrom"].as_str() {
            h["_meta"][agent.domain()]["agentForkedFrom"] = json!(fork);
        }
        if let Some(t) = helpers::time(&native["created_at"]) {
            h["startedAt"] = json!(t);
        }
    }
    privacy::questions(s, &native)?;
    s.session(&key, &h)?;
    // All known secret answers are collected before any native observation is persisted.
    let mut answers = Reader::new(reader(path)?, s.limit);
    while let Some(line) = answers.read()? {
        if let Line::Record(v) = line {
            privacy::answers(s, &v)?;
        }
    }
    s.has_secrets =
        s.db.query_row("SELECT EXISTS(SELECT 1 FROM secrets)", [], |r| r.get(0))?;
    let mut input = Reader::new(reader(path)?, s.limit);
    while let Some(line) = input.read()? {
        match line {
            Line::Record(mut v) => {
                let mut target = key.clone();
                if agent == Agent::CopilotCli {
                    if let Some(child) = string(&v["agentId"]) {
                        let child = child.to_owned();
                        target = json!([id, child]).to_string();
                        let mut ch = h.clone();
                        ch["sessionId"] = json!(child);
                        ch["namespace"] = json!(id);
                        ch["parent"] =
                            json!({"kind":"subagent","session":session_ref(agent.name(),None,&id)});
                        s.session(&target, &ch)?;
                    }
                }
                if agent == Agent::GrokBuild {
                    if let Some(other) = identity(agent, &v) {
                        target = other.into();
                        s.session(&target, &header(agent, other, &v))?;
                    }
                }
                if agent == Agent::DeepSeekHarness {
                    if let (Some(parent), Some(seed), Some(seq)) = (
                        string(&native["parentSession"]),
                        native["seedLength"].as_u64(),
                        v["seq"].as_u64(),
                    ) {
                        if seq < seed {
                            v["_asrCopy"] =
                                json!({"session":session_ref(agent.name(),None,parent)});
                        }
                    }
                }
                if privacy::sanitize(s, &mut v)? {
                    v["_asrRedacted"] = json!(true);
                    summary.diagnostic("secret_redacted");
                }
                let identity = match agent {
                    Agent::Tabnine => string(&v["id"]).map(|id| format!("message:{id}")),
                    Agent::QwenCode => string(&v["uuid"]).map(|id| format!("uuid:{id}")),
                    Agent::Antigravity => v["step_index"].as_u64().map(|n| format!("step:{n}")),
                    _ => None,
                };
                s.push(&target, &v, identity.as_deref())?;
            }
            Line::Malformed | Line::Oversized => {
                s.push(
                    &key,
                    &json!({"type":"_gap","record":gap("unparseable")}),
                    None,
                )?;
                summary.diagnostic("unparseable_source_line");
            }
            Line::Incomplete => {
                summary.diagnostic("incomplete_source_tail");
                if agent == Agent::KimiCode {
                    s.push(
                        &key,
                        &json!({"type":"_gap","record":gap("not_retained")}),
                        None,
                    )?;
                }
            }
        }
    }
    summary.source_bytes += input.bytes;
    Ok(())
}
