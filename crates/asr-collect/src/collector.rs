use crate::{util::*, CollectArgs, Error, Failure, Result, Target};
use asr_convert::Agent;
use notify::{RecursiveMode, Watcher};
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::{Path, PathBuf},
    sync::mpsc,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

#[derive(Debug, Default, Serialize)]
pub struct CollectionSummary {
    pub source_files: u64,
    pub identified_sessions: u64,
    pub converted_sessions: u64,
    pub uploaded_sessions: u64,
    pub unchanged_sessions: u64,
    pub failures: u64,
    pub diagnostics: BTreeMap<String, u64>,
}
impl CollectionSummary {
    fn diagnostic(&mut self, code: &str, count: u64) {
        *self.diagnostics.entry(code.into()).or_default() += count;
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
struct Metadata {
    length: u64,
    modified_ns: u128,
    #[cfg(unix)]
    changed_seconds: i64,
    #[cfg(unix)]
    changed_nanos: i64,
}
fn metadata(path: &Path) -> Result<Metadata> {
    let meta = fs::metadata(path)?;
    #[cfg(unix)]
    use std::os::unix::fs::MetadataExt;
    Ok(Metadata {
        length: meta.len(),
        modified_ns: meta
            .modified()?
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos(),
        #[cfg(unix)]
        changed_seconds: meta.ctime(),
        #[cfg(unix)]
        changed_nanos: meta.ctime_nsec(),
    })
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
struct SourceMetadata {
    files: BTreeMap<PathBuf, Metadata>,
    modified_ns: u128,
}
fn source_metadata(agent: Agent, path: &Path) -> Result<SourceMetadata> {
    let files = asr_convert::source_dependencies(agent, path)?
        .into_iter()
        .map(|p| Ok((p.clone(), metadata(&p)?)))
        .collect::<Result<BTreeMap<_, _>>>()?;
    let modified_ns = files.values().map(|m| m.modified_ns).max().unwrap_or(0);
    Ok(SourceMetadata { files, modified_ns })
}
fn source_digest(snapshot: &SourceMetadata) -> Result<String> {
    let hashes = snapshot
        .files
        .keys()
        .map(|p| Ok((p, hash_file(p)?.0)))
        .collect::<Result<Vec<_>>>()?;
    Ok(digest(&serde_json::to_vec(&hashes)?))
}

#[derive(Clone, Serialize, Deserialize)]
struct SourceState {
    metadata: SourceMetadata,
    sha256: String,
    sessions: Vec<String>,
}
#[derive(Clone, Serialize, Deserialize, Default)]
struct SessionState {
    signature: String,
    sha256: String,
}
#[derive(Clone, Serialize, Deserialize)]
struct Pending {
    signature: String,
    sha256: String,
    request: String,
}
#[derive(Serialize, Deserialize)]
struct State {
    version: u32,
    machine: String,
    binding: String,
    sources: BTreeMap<String, SourceState>,
    sessions: BTreeMap<String, SessionState>,
    pending: BTreeMap<String, Pending>,
}
struct Source {
    path: PathBuf,
    cache_key: String,
    cached: SourceState,
}
struct Group {
    agent: Agent,
    sources: Vec<Source>,
    newest: u128,
}
struct Collector {
    args: CollectArgs,
    state: State,
    roots: Vec<(Agent, PathBuf)>,
    target: Target,
    validator: PathBuf,
    _lock: FileLock,
}

pub fn collect(args: CollectArgs, validator: &Path) -> Result<CollectionSummary> {
    let mut collector = Collector::open(args, validator)?;
    if !collector.args.watch {
        return collector.scan_recorded();
    }
    let (send, events) = mpsc::sync_channel(1);
    let mut watcher = if collector.args.poll_only {
        None
    } else {
        notify::recommended_watcher(move |event: notify::Result<notify::Event>| {
            if event.as_ref().map_or(true, |e| !e.kind.is_access()) {
                let _ = send.try_send(());
            }
        })
        .ok()
    };
    if let Some(watcher) = watcher.as_mut() {
        for (_, root) in &collector.roots {
            let watch = if root.is_file() {
                root.parent().unwrap_or(root)
            } else {
                root.as_path()
            };
            if watcher.watch(watch, RecursiveMode::Recursive).is_err() {
                eprintln!(
                    "asr collect: file events unavailable for a root, polling remains active"
                );
            }
        }
    } else if !collector.args.poll_only {
        eprintln!("asr collect: file events unavailable, using polling");
    }
    loop {
        match collector.scan_recorded() {
            Ok(summary) => println!("{}", serde_json::to_string(&summary)?),
            Err(_) => {
                eprintln!("asr collect: scan failed, saved checkpoints retained for retry");
            }
        }
        // Always poll, even if the operating system drops an event.
        match events.recv_timeout(Duration::from_secs(collector.args.poll_seconds)) {
            Ok(()) => {
                std::thread::sleep(Duration::from_millis(200));
                while events.try_recv().is_ok() {}
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                std::thread::sleep(Duration::from_secs(collector.args.poll_seconds))
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {}
        }
    }
}

impl Collector {
    fn open(args: CollectArgs, validator: &Path) -> Result<Self> {
        if args.poll_seconds == 0
            || args.max_record_bytes < 1024
            || args.max_sessions == Some(0)
            || args.recent_hours == Some(0)
        {
            return Err(Error::Invalid(
                "collection bounds must be positive and record bytes at least 1024",
            ));
        }
        private_dir(&args.state)?;
        let lock = lock(&args.state.join("collector.lock"))?;
        let roots = roots(&args)?;
        if roots.is_empty() {
            return Err(Error::Invalid(
                "no supported discovery roots are configured",
            ));
        }
        let binding = digest(&serde_json::to_vec(&serde_json::json!({
            "target":args.target,"uploader":args.uploader,"roots":roots.iter().map(|(a,p)|(a.name(),p)).collect::<Vec<_>>(),
            "namespace":args.namespace,"window":args.window_seconds,"recordLimit":args.max_record_bytes
        }))?);
        let state_path = args.state.join("state.json");
        let state: State = if state_path.exists() {
            let state: State =
                serde_json::from_slice(&private_file_limit(&state_path, 64 * 1024 * 1024)?)?;
            if state.version != 2
                || state.binding != binding
                || args.machine.as_ref().is_some_and(|m| m != &state.machine)
            {
                return Err(Error::Invalid(
                    "saved state belongs to a different machine, target or source configuration",
                ));
            }
            state
        } else {
            State {
                version: 2,
                machine: args
                    .machine
                    .clone()
                    .unwrap_or_else(|| uuid::Uuid::new_v4().to_string()),
                binding,
                sources: BTreeMap::new(),
                sessions: BTreeMap::new(),
                pending: BTreeMap::new(),
            }
        };
        if !valid_machine(&state.machine) {
            return Err(Error::Invalid("invalid machine ID"));
        }
        let target = Target::open(
            &args.target,
            &args.state,
            args.uploader.as_deref(),
            args.token_file.as_deref(),
            args.window_seconds,
            validator,
        )?;
        let mut outputs = vec![fs::canonicalize(&args.state)?];
        match &target {
            Target::Local { store, .. } | Target::Cloud { store, .. } => {
                outputs.push(fs::canonicalize(store.root())?)
            }
            _ => {}
        }
        for (_, root) in &roots {
            if root.is_dir() {
                let root = fs::canonicalize(root)?;
                if outputs.iter().any(|p| p.starts_with(&root)) {
                    return Err(Error::Invalid(
                        "state and target must be outside native source directories",
                    ));
                }
            }
        }
        let collector = Self {
            args,
            state,
            roots,
            target,
            validator: validator.to_owned(),
            _lock: lock,
        };
        collector.save()?;
        Ok(collector)
    }

    fn save(&self) -> Result<()> {
        atomic_write(
            &self.args.state.join("state.json"),
            &serde_json::to_vec(&self.state)?,
        )
    }

    fn scan_recorded(&mut self) -> Result<CollectionSummary> {
        let result = self.scan();
        if let Err(error) = &result {
            let _ = self.scan_failure(error);
        }
        result
    }

    fn scan_failure(&mut self, error: &Error) -> Result<()> {
        // Error displays are deliberately private and may merge distinct I/O failures.
        let code = match error {
            Error::Io(e) => format!("io:{:?}", e.kind()),
            Error::Json(_) => "json".into(),
            Error::Sql(_) => "sql".into(),
            Error::Convert(_) => "convert".into(),
            Error::Http(_) => "http".into(),
            Error::Object(_) => "object".into(),
            Error::Invalid(message) => format!("invalid:{message}"),
        };
        let request = digest(&serde_json::to_vec(&(
            "scan-failure",
            &self.state.binding,
            code,
            self.args.recent_hours,
            self.args.max_sessions,
        ))?);
        self.target.failure(
            &self.state.machine,
            &request,
            Failure {
                reason: "Local discovery or collection failed.",
                session: None,
            },
        )
    }

    fn scan(&mut self) -> Result<CollectionSummary> {
        let mut summary = CollectionSummary::default();
        let mut groups: BTreeMap<String, Group> = BTreeMap::new();
        let mut cache = BTreeMap::new();
        let mut seen = BTreeSet::new();
        for (agent, root) in &self.roots {
            if !root.exists() {
                // Missing default locations are ordinary. Explicit roots must be reachable.
                if !self.args.sources.is_empty() {
                    return Err(Error::Invalid("a configured source root is unavailable"));
                }
                continue;
            }
            for path in asr_convert::discover_agent(*agent, root, &self.args.state)? {
                let canonical = fs::canonicalize(&path)?;
                let key = serde_json::to_string(&(agent.name(), &canonical))?;
                if !seen.insert(key.clone()) {
                    continue;
                }
                let before = source_metadata(*agent, &path)?;
                let cached = match self.state.sources.get(&key) {
                    Some(cached) if cached.metadata == before => cached.clone(),
                    _ => {
                        let sha256 = source_digest(&before)?;
                        let inventory = tempfile::Builder::new()
                            .prefix("inventory-")
                            .tempdir_in(&self.args.state)?;
                        let mut options = asr_convert::Options::new(
                            *agent,
                            path.clone(),
                            inventory.path().to_owned(),
                        );
                        options.max_record_bytes = self.args.max_record_bytes;
                        options.namespace = self.args.namespace.clone();
                        let sessions = match asr_convert::identify_sources(&options, &path) {
                            Ok(sessions) => sessions,
                            Err(_) => {
                                summary.failures += 1;
                                summary.diagnostic("source_inventory_failed", 1);
                                let _ = self.target.failure(
                                    &self.state.machine,
                                    &digest(&serde_json::to_vec(&(
                                        "inventory-failure",
                                        &key,
                                        &sha256,
                                    ))?),
                                    Failure {
                                        reason: "Native source identity inventory failed.",
                                        session: None,
                                    },
                                );
                                continue;
                            }
                        };
                        if source_metadata(*agent, &path)? != before {
                            return Err(Error::Invalid(
                                "source changed during discovery, retry required",
                            ));
                        }
                        SourceState {
                            metadata: before,
                            sha256,
                            sessions,
                        }
                    }
                };
                summary.source_files += 1;
                if cached.sessions.is_empty() {
                    summary.diagnostic("unidentified_source", 1);
                }
                for session in &cached.sessions {
                    let group = groups.entry(session.clone()).or_insert_with(|| Group {
                        agent: *agent,
                        sources: Vec::new(),
                        newest: 0,
                    });
                    group.newest = group.newest.max(cached.metadata.modified_ns);
                    group.sources.push(Source {
                        path: path.clone(),
                        cache_key: key.clone(),
                        cached: cached.clone(),
                    });
                }
                cache.insert(key, cached);
            }
        }
        self.state.sources = cache;
        self.save()?;
        summary.identified_sessions = groups.len() as u64;
        let mut groups: Vec<_> = groups.into_iter().collect();
        groups.sort_by(|(a, x), (b, y)| y.newest.cmp(&x.newest).then(a.cmp(b)));
        let recent = self.args.recent_hours.map(|h| {
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
                .saturating_sub(u128::from(h) * 3600 * 1_000_000_000)
        });
        let mut attempted = 0;
        for (session, mut group) in groups {
            group.sources.sort_by(|a, b| a.path.cmp(&b.path));
            if recent.is_some_and(|cutoff| group.newest < cutoff) {
                continue;
            }
            let signature = digest(&serde_json::to_vec(
                &group
                    .sources
                    .iter()
                    .map(|s| (&s.cache_key, &s.cached.sha256))
                    .collect::<Vec<_>>(),
            )?);
            if self
                .state
                .sessions
                .get(&session)
                .is_some_and(|s| s.signature == signature)
            {
                summary.unchanged_sessions += 1;
                continue;
            }
            if self.args.max_sessions.is_some_and(|n| attempted >= n) {
                continue;
            }
            attempted += 1;
            match self.convert_group(&session, &group, &signature, &mut summary) {
                Ok(()) => {}
                Err(_) => {
                    summary.failures += 1;
                    summary.diagnostic("session_collection_failed", 1);
                    let _ = self.target.failure(
                        &self.state.machine,
                        &digest(&serde_json::to_vec(&(
                            "session-failure",
                            &session,
                            &signature,
                        ))?),
                        Failure {
                            reason: "Session conversion, validation or upload failed.",
                            session: Some(&session),
                        },
                    );
                }
            }
        }
        self.target.heartbeat(&self.state.machine)?;
        self.save()?;
        Ok(summary)
    }

    fn convert_group(
        &mut self,
        session: &str,
        group: &Group,
        signature: &str,
        summary: &mut CollectionSummary,
    ) -> Result<()> {
        let output = tempfile::Builder::new()
            .prefix("conversion-")
            .tempdir_in(&self.args.state)?;
        let paths: Vec<_> = group.sources.iter().map(|s| s.path.clone()).collect();
        let options = asr_convert::Options {
            agent: group.agent,
            input: paths[0].clone(),
            out: output.path().to_owned(),
            max_record_bytes: self.args.max_record_bytes,
            namespace: self.args.namespace.clone(),
        };
        let converted = asr_convert::convert_session_files(&options, &paths, session)?;
        for (code, count) in converted.diagnostics {
            summary.diagnostic(&format!("conversion:{code}"), count);
        }
        if converted.sessions != 1 {
            return Err(Error::Invalid(
                "source group did not produce exactly one session",
            ));
        }
        for source in &group.sources {
            if source_metadata(group.agent, &source.path)? != source.cached.metadata {
                return Err(Error::Invalid(
                    "source changed during conversion, retry required",
                ));
            }
        }
        let files: Vec<_> = fs::read_dir(output.path())?
            .collect::<std::result::Result<Vec<_>, _>>()?
            .into_iter()
            .map(|e| e.path())
            .filter(|p| p.extension().is_some_and(|e| e == "jsonl"))
            .collect();
        if files.len() != 1 {
            return Err(Error::Invalid("converted session file was not found"));
        }
        let path = &files[0];
        let valid = validate_file(&self.validator, path)?;
        for (code, count) in valid.counts {
            summary.diagnostic(&format!("validation:{code}"), count);
        }
        if valid.errors > 0 {
            return Err(Error::Invalid("converted session failed validation"));
        }
        summary.converted_sessions += 1;
        let (sha256, _) = hash_file(path)?;
        if self
            .state
            .sessions
            .get(session)
            .is_some_and(|s| s.sha256 == sha256)
        {
            self.state.sessions.insert(
                session.into(),
                SessionState {
                    signature: signature.into(),
                    sha256,
                },
            );
            self.state.pending.remove(session);
            self.save()?;
            return Ok(());
        }
        let pending = self
            .state
            .pending
            .get(session)
            .filter(|p| p.signature == signature && p.sha256 == sha256)
            .cloned()
            .unwrap_or_else(|| Pending {
                signature: signature.into(),
                sha256: sha256.clone(),
                request: uuid::Uuid::new_v4().to_string(),
            });
        self.state.pending.insert(session.into(), pending.clone());
        self.save()?;
        self.target
            .send(&self.state.machine, &pending.request, path)?;
        self.state.sessions.insert(
            session.into(),
            SessionState {
                signature: signature.into(),
                sha256,
            },
        );
        self.state.pending.remove(session);
        self.save()?;
        summary.uploaded_sessions += 1;
        Ok(())
    }
}

fn roots(args: &CollectArgs) -> Result<Vec<(Agent, PathBuf)>> {
    let mut roots = Vec::new();
    for source in &args.sources {
        let (agent, path) = source
            .split_once('=')
            .ok_or(Error::Invalid("sources use agent=path"))?;
        let agent: Agent = agent
            .parse()
            .map_err(|_| Error::Invalid("source names an unsupported agent"))?;
        if path.is_empty() || !args.agents.is_empty() && !args.agents.contains(&agent) {
            continue;
        }
        roots.push((agent, PathBuf::from(path)));
    }
    if args.sources.is_empty() {
        let home = std::env::var_os("HOME")
            .map(PathBuf::from)
            .ok_or(Error::Invalid("default discovery needs HOME"))?;
        for agent in Agent::ALL {
            if !args.agents.is_empty() && !args.agents.contains(&agent) {
                continue;
            }
            roots.extend(
                crate::discovery::default_roots(agent, &home, &std::env::current_dir()?)
                    .into_iter()
                    .map(|p| (agent, p)),
            );
        }
    }
    if args.sources.is_empty() && args.agents.is_empty() {
        prefer_current_alias_root(&mut roots);
    }
    Ok(roots)
}

fn prefer_current_alias_root(roots: &mut Vec<(Agent, PathBuf)>) {
    let current: Vec<_> = roots
        .iter()
        .filter(|(agent, _)| *agent == Agent::Xum)
        .map(|(_, path)| path.clone())
        .collect();
    roots.retain(|(agent, path)| *agent != Agent::Mux || !current.contains(path));
}

#[cfg(test)]
mod tests {
    use super::*;
    use clap::Parser;
    #[derive(Parser)]
    struct TestArgs {
        #[command(flatten)]
        args: CollectArgs,
    }

    #[test]
    fn default_discovery_visits_a_shared_legacy_xum_root_once() {
        let mut roots = vec![
            (Agent::Mux, PathBuf::from("/legacy/sessions")),
            (Agent::Xum, PathBuf::from("/legacy/sessions")),
            (Agent::Mux, PathBuf::from("/separate/sessions")),
        ];
        prefer_current_alias_root(&mut roots);
        assert_eq!(
            roots,
            vec![
                (Agent::Xum, PathBuf::from("/legacy/sessions")),
                (Agent::Mux, PathBuf::from("/separate/sessions")),
            ]
        );
    }

    #[test]
    fn whole_scan_failure_receipts_are_stable_across_retries_and_restarts() {
        let temp = tempfile::tempdir().unwrap();
        let source = temp.path().join("source");
        fs::create_dir(&source).unwrap();
        let state = temp.path().join("state");
        let target = temp.path().join("store");
        let validator =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tools/validator/bin/asr-validate.js");
        let args = TestArgs::parse_from([
            "test",
            "--target",
            target.to_str().unwrap(),
            "--state",
            state.to_str().unwrap(),
            "--source",
            &format!("claude-code={}", source.display()),
            "--machine",
            "synthetic-machine",
            "--uploader",
            "synthetic-user",
        ])
        .args;
        let mut collector = Collector::open(args.clone(), &validator).unwrap();
        fs::remove_dir(&source).unwrap();
        for _ in 0..3 {
            assert!(collector.scan_recorded().is_err());
        }
        drop(collector);
        let mut collector = Collector::open(args, &validator).unwrap();
        assert!(collector.scan_recorded().is_err());
        collector
            .scan_failure(&Error::Io(std::io::ErrorKind::PermissionDenied.into()))
            .unwrap();
        collector
            .scan_failure(&Error::Io(std::io::ErrorKind::PermissionDenied.into()))
            .unwrap();
        collector
            .scan_failure(&Error::Io(std::io::ErrorKind::NotFound.into()))
            .unwrap();
        drop(collector);
        let db = rusqlite::Connection::open(target.join("receipts.sqlite3")).unwrap();
        let count: u64 = db
            .query_row("SELECT count(*) FROM receipts", [], |r| r.get(0))
            .unwrap();
        assert_eq!(count, 3);
    }
}
