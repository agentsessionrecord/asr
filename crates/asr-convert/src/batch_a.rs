//! Storage helpers for the transcript and snapshot adapters.
use crate::{common::Context, privacy, spool::Spool, Agent, Error, Result, Summary};
use asr_core::jsonl::{decode, Line, Reader};
use serde_json::{json, Value};
use std::{fs::File, io::Read, path::Path};

pub fn handles(agent: Agent) -> bool {
    matches!(
        agent,
        Agent::Cursor | Agent::GeminiCli | Agent::MistralVibe | Agent::Mux | Agent::Xum | Agent::Fx
    )
}
pub fn discover(
    input: &Path,
    agent: Agent,
    mut visit: impl FnMut(std::path::PathBuf) -> Result<()>,
) -> Result<()> {
    if input.is_file() || input.join("CURRENT").is_file() {
        return visit(input.to_owned());
    }
    for entry in walkdir::WalkDir::new(input)
        .sort_by_file_name()
        .follow_links(false)
        .max_open(16)
        .into_iter()
        .filter_entry(|e| {
            // Committed stores are admitted as units. Never read obsolete generations.
            e.depth() == 0
                || !e
                    .path()
                    .parent()
                    .is_some_and(|p| p.join("CURRENT").is_file())
        })
    {
        let entry = entry.map_err(|_| Error::Invalid("source inventory failed".into()))?;
        let store = agent == Agent::MistralVibe
            && entry.file_type().is_dir()
            && entry.path().join("CURRENT").is_file();
        let file = (entry.file_type().is_file()
            || entry.file_type().is_symlink() && entry.path().is_file())
            && candidate(entry.path(), agent);
        if store || file {
            visit(entry.path().to_owned())?;
        }
    }
    Ok(())
}
fn candidate(p: &Path, a: Agent) -> bool {
    let name = p.file_name().and_then(|v| v.to_str()).unwrap_or_default();
    let plain = name.trim_end_matches(".zst").trim_end_matches(".zstd");
    if plain != name && p.with_extension("").is_file() {
        return false;
    }
    match a {
        Agent::Cursor => plain.ends_with(".jsonl"),
        Agent::GeminiCli => {
            plain.ends_with(".jsonl")
                || name.ends_with(".json") && !p.with_extension("jsonl").is_file()
        }
        Agent::MistralVibe => plain == "messages.jsonl",
        Agent::Mux | Agent::Xum => {
            matches!(plain, "chat.jsonl" | "chat-archive.jsonl") || name == "partial.json"
        }
        Agent::Fx => name == "events.jsonl",
        _ => false,
    }
}
pub(crate) fn stage(p: &Path, a: Agent, s: &mut Spool, n: &mut Summary) -> Result<()> {
    if a == Agent::MistralVibe && p.is_dir() && p.join("CURRENT").is_file() {
        return crate::mistral_vibe::unified(s, p, n);
    }
    if !candidate(p, a) {
        return Ok(());
    }
    let canonical = std::fs::canonicalize(p)?;
    if s.db.execute(
        "INSERT OR IGNORE INTO sources VALUES(?1)",
        [canonical.to_string_lossy().as_ref()],
    )? == 0
    {
        return Ok(());
    }
    match a {
        Agent::Cursor => crate::cursor::stage(s, p, n),
        Agent::GeminiCli => crate::gemini::stage(s, p, n),
        Agent::MistralVibe => crate::mistral_vibe::stage(s, p, n),
        Agent::Mux | Agent::Xum => crate::mux::stage(s, p, n, a),
        Agent::Fx => crate::fx::stage(s, p, n),
        _ => unreachable!(),
    }
}
pub(crate) use crate::source::reader;
pub fn document(p: &Path, limit: usize) -> Result<Value> {
    let mut bytes = Vec::new();
    File::open(p)?
        .take(limit as u64 + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() > limit {
        return Err(Error::Invalid(
            "native document exceeded record bound".into(),
        ));
    }
    let raw = std::str::from_utf8(&bytes)
        .map_err(|_| Error::Invalid("native document is not UTF-8".into()))?;
    decode(raw).map_err(Into::into)
}
pub use crate::common::header;
pub use crate::common::{nonempty, timestamp_millis as timestamp};
pub fn time(c: &mut Context, v: &Value) {
    c.source.as_object_mut().unwrap().remove("ts");
    if let Some(ts) = timestamp(v) {
        c.source["ts"] = json!(ts);
    }
}
pub fn push(s: &mut Spool, id: &str, mut v: Value, n: &mut Summary) -> Result<()> {
    privacy::questions(s, &v)?;
    privacy::answers(s, &v)?;
    s.has_secrets =
        s.db.query_row("SELECT EXISTS(SELECT 1 FROM secrets)", [], |r| r.get(0))?;
    if privacy::sanitize(s, &mut v)? {
        v["_asrRedacted"] = json!(true);
        n.diagnostic("secret_redacted");
    }
    if privacy::scrub_opaque(&mut v, false) {
        v["_asrOpaqueOmitted"] = json!(true);
    }
    s.push(id, &v, None)
}
pub fn lines(s: &mut Spool, p: &Path, id: &str, n: &mut Summary) -> Result<()> {
    // Establish marked answers before any native row reaches the disk index.
    for answers in [false, true] {
        let mut scan = Reader::new(reader(p)?, s.limit);
        while let Some(line) = scan.read()? {
            if let Line::Record(v) = line {
                if answers {
                    privacy::answers(s, &v)?;
                } else {
                    privacy::questions(s, &v)?;
                }
            }
        }
    }
    let mut r = Reader::new(reader(p)?, s.limit);
    while let Some(line) = r.read()? {
        match line {
            Line::Record(v) => push(s, id, v, n)?,
            Line::Malformed | Line::Oversized => {
                push(
                    s,
                    id,
                    json!({"type":"_gap","record":{"type":"gap","reason":"unparseable","count":1}}),
                    n,
                )?;
                n.diagnostic("unparseable_source_line");
            }
            Line::Incomplete => n.diagnostic("incomplete_source_tail"),
        }
    }
    n.source_bytes += r.bytes;
    n.files += 1;
    Ok(())
}
pub fn call(
    s: &Spool,
    c: &mut Context,
    native: &Value,
    call: Option<&str>,
    name: Option<&str>,
    args: Option<&Value>,
    fold: Option<&str>,
) -> Result<String> {
    let id = call.map(str::to_owned).unwrap_or_else(|| {
        asr_core::identity::derive_id(&[
            &c.session,
            &c.ordinal.to_string(),
            &c.slot.to_string(),
            "call",
        ])
    });
    let mut r = json!({"type":"tool_call","callId":id,"requestedBy":"model"});
    if let Some(name) = name {
        r["name"] = json!(name);
    }
    if let Some(args) = args {
        r[if args.is_string() {
            "inputText"
        } else {
            "input"
        }] = args.clone();
    }
    r["_meta"] = json!({c.agent.domain():{"native":native}});
    c.emit(s, r, None, fold)?;
    Ok(id)
}
pub fn gap(s: &Spool, c: &mut Context, v: &Value) -> Result<bool> {
    if v["type"] == "_gap" {
        c.emit(s, v["record"].clone(), None, None)?;
        Ok(true)
    } else {
        Ok(false)
    }
}
pub fn vendor_part(a: Agent, v: &Value) -> Value {
    crate::common::vendor_part(a, v)
}
pub use crate::common::count;
