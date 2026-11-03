//! Collection uses the same native inventory and staging as offline conversion.
use crate::{batch_a, documents, source, spool::Spool, sqlite, Agent, Options, Result, Summary};
use std::path::{Path, PathBuf};

pub(super) fn stage_isolated(
    spool: &mut Spool,
    options: &Options,
    paths: &[PathBuf],
    summary: &mut Summary,
) -> Result<()> {
    // Roll back a failed source's partial staging while retaining independent sources.
    let mut ordered = paths.to_vec();
    ordered.sort_by_key(|p| documents::natural_key(p));
    for (index, path) in ordered.iter().enumerate() {
        let before: i64 =
            spool
                .db
                .query_row("SELECT coalesce(max(pos),0) FROM native", [], |r| r.get(0))?;
        let before_session: i64 =
            spool
                .db
                .query_row("SELECT coalesce(max(rowid),0) FROM sessions", [], |r| {
                    r.get(0)
                })?;
        let before_secret_bytes = spool.secret_bytes.get();
        spool.db.execute_batch("SAVEPOINT source_file")?;
        match stage_files(spool, options, std::slice::from_ref(path), summary) {
            Ok(()) => {
                spool.db.execute_batch("RELEASE source_file")?;
            }
            Err(error) => {
                if matches!(&error, crate::Error::Invalid(message) if message.contains("namespace"))
                {
                    return Err(error);
                }
                let mut statement = spool.db.prepare("SELECT DISTINCT sessions.header FROM sessions LEFT JOIN native ON native.session=sessions.id WHERE native.pos>?1 OR sessions.rowid>?2")?;
                let headers: Vec<String> = statement
                    .query_map([before, before_session], |r| r.get(0))?
                    .collect::<std::result::Result<_, _>>()?;
                drop(statement);
                spool
                    .db
                    .execute_batch("ROLLBACK TO source_file; RELEASE source_file")?;
                spool.has_secrets =
                    spool
                        .db
                        .query_row("SELECT EXISTS(SELECT 1 FROM secrets)", [], |r| r.get(0))?;
                spool.secret_bytes.set(before_secret_bytes);
                *spool.secret_matcher.borrow_mut() = None;
                if headers.is_empty() {
                    summary
                        .diagnostic_for(&format!("source-{}", index + 1), "source_staging_failed");
                }
                let mut failed = Vec::new();
                for raw in headers {
                    let header: serde_json::Value = serde_json::from_str(&raw)?;
                    let reference = asr_core::identity::session_ref(
                        options.agent.name(),
                        header["namespace"].as_str(),
                        header["sessionId"].as_str().unwrap_or("unknown"),
                    );
                    summary.diagnostic_for(&reference, "source_staging_failed");
                    failed.push(reference);
                }
                // Single-source API callers keep their explicit failure contract.
                if paths.len() == 1 {
                    return Err(crate::Error::Invalid(format!(
                        "{}: source_staging_failed",
                        if failed.is_empty() {
                            format!("source-{}", index + 1)
                        } else {
                            failed.join(", ")
                        }
                    )));
                }
            }
        }
    }
    Ok(())
}

pub fn discover_agent(agent: Agent, input: &Path, out: &Path) -> Result<Vec<PathBuf>> {
    let mut paths = Vec::new();
    let mut visit = |path| {
        paths.push(path);
        Ok(())
    };
    if batch_a::handles(agent) {
        batch_a::discover(input, agent, &mut visit)?;
    } else if sqlite::handles(agent) {
        sqlite::discover_paths(agent, input, out, &mut visit)?;
    } else if documents::handles(agent) {
        documents::discover(input, out, agent, &mut visit)?;
    } else {
        source::discover(input, out, &mut visit)?;
    }
    Ok(paths)
}

pub(super) fn stage_files(
    spool: &mut Spool,
    options: &Options,
    paths: &[PathBuf],
    summary: &mut Summary,
) -> Result<()> {
    let mut ordered = paths.to_vec();
    if documents::handles(options.agent) {
        ordered.sort_by_key(|p| documents::natural_key(p));
    }
    for path in &ordered {
        if batch_a::handles(options.agent) {
            batch_a::stage(path, options.agent, spool, summary)?;
        } else if sqlite::handles(options.agent) {
            let mut selected = options.clone();
            selected.input = path.clone();
            sqlite::discover(spool, &selected, &options.out, summary)?;
        } else if documents::handles(options.agent) {
            documents::stage(spool, options.agent, path, summary)?;
        } else {
            source::stage(spool, options.agent, path, summary)?;
        }
    }
    Ok(())
}

/// A database or snapshot can contain several recorded sessions.
pub fn identify_sources(options: &Options, path: &Path) -> Result<Vec<String>> {
    crate::common::private_dir(&options.out)?;
    let mut spool = Spool::new(&options.out, options.max_record_bytes)?;
    stage_files(
        &mut spool,
        options,
        &[path.to_owned()],
        &mut Summary::default(),
    )?;
    let mut sessions = Vec::new();
    let mut previous = String::new();
    while let Some((id, header)) = spool.next_session(&previous)? {
        previous = id.clone();
        sessions.push(asr_core::identity::session_ref(
            options.agent.name(),
            header["namespace"].as_str(),
            header["sessionId"].as_str().ok_or_else(|| {
                crate::Error::Invalid("native session identity is missing".into())
            })?,
        ));
    }
    Ok(sessions)
}

fn tree(path: &Path, paths: &mut Vec<PathBuf>) -> Result<()> {
    if !path.exists() {
        return Ok(());
    }
    if path.is_file() {
        paths.push(path.to_owned());
        return Ok(());
    }
    for entry in walkdir::WalkDir::new(path).follow_links(false).max_open(16) {
        let entry = entry
            .map_err(|_| crate::Error::Invalid("source dependencies could not be read".into()))?;
        if entry.file_type().is_file() {
            paths.push(entry.into_path());
        }
    }
    Ok(())
}

/// Include companion metadata, snapshot components and live SQLite WAL bytes.
pub fn source_dependencies(agent: Agent, path: &Path) -> Result<Vec<PathBuf>> {
    let mut paths = Vec::new();
    tree(path, &mut paths)?;
    let parent = path.parent().unwrap_or(Path::new("."));
    match agent {
        Agent::MistralVibe if path.is_file() => tree(&parent.join("meta.json"), &mut paths)?,
        Agent::Fx => tree(parent, &mut paths)?,
        Agent::KimiCode => {
            if let Some(session) = parent
                .parent()
                .filter(|p| p.ends_with("agents"))
                .and_then(Path::parent)
            {
                tree(&session.join("state.json"), &mut paths)?;
                tree(&session.join("session-meta/state.json"), &mut paths)?;
            }
        }
        Agent::Mux | Agent::Xum => {
            for name in ["metadata.json", "subagent-transcripts.json", "partial.json"] {
                tree(&parent.join(name), &mut paths)?;
            }
        }
        Agent::Cline | Agent::RooCode => tree(&parent.join("task_metadata.json"), &mut paths)?,
        Agent::CodeBuddy if path.file_name().is_some_and(|n| n == "index.json") => {
            tree(&parent.join("messages"), &mut paths)?
        }
        Agent::NanoClaw => tree(&parent.join("v2-sessions"), &mut paths)?,
        Agent::OpenClaw => {
            if let Some(root) = path
                .ancestors()
                .find(|p| p.file_name().is_some_and(|n| n == "agents"))
                .and_then(Path::parent)
            {
                tree(&root.join("state/openclaw.sqlite"), &mut paths)?;
            }
        }
        _ => {}
    }
    for file in paths.clone() {
        let mut wal = file.into_os_string();
        wal.push("-wal");
        tree(Path::new(&wal), &mut paths)?;
    }
    paths.sort();
    paths.dedup();
    Ok(paths)
}
