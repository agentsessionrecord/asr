use asr_collect::{
    collect, hash_file, validate_file, CollectArgs, Failure, ReceiptStore, ReceiveArgs, Receiver,
};
use chrono::{DateTime, Utc};
use serde_json::{json, Value};
use std::{
    fs,
    io::Write,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::Duration,
};

fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}
fn validator() -> PathBuf {
    repo().join("tools/validator/bin/asr-validate.js")
}
fn at(seconds: i64) -> DateTime<Utc> {
    DateTime::from_timestamp(seconds, 0).unwrap()
}
fn sample(id: &str) -> Vec<u8> {
    format!("{}\n{}\n",json!({"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"com.example.agent"},
        "namespace":"install:7","sessionId":id,"producer":{"name":"test","version":"1","method":"native"},"user":{"id":"recorded-person"}}),
        r#"{"type":"com.example.agent/extra","id":"future","data":{"exact":123456789012345678901234567890,"decimal":0.1234567890123456789}}"#).into_bytes()
}
fn write(path: &Path, bytes: &[u8]) {
    fs::write(path, bytes).unwrap();
}
fn manifests(root: &Path) -> Vec<PathBuf> {
    let mut files = Vec::new();
    for machine in fs::read_dir(root.join("manifests")).unwrap() {
        for file in fs::read_dir(machine.unwrap().path()).unwrap() {
            files.push(file.unwrap().path());
        }
    }
    files.sort();
    files
}
fn check_manifests(root: &Path) -> Vec<Value> {
    manifests(root)
        .iter()
        .map(|p| {
            let valid = validate_file(&validator(), p).unwrap();
            assert_eq!(valid.errors, 0);
            assert_eq!(valid.warnings, 0);
            serde_json::from_slice(&fs::read(p).unwrap()).unwrap()
        })
        .collect()
}

#[test]
fn exact_bytes_replacements_retries_and_empty_windows_survive_restart() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path().join("store");
    let source = tmp.path().join("session.jsonl");
    let original = sample("run:7");
    write(&source, &original);
    let mut store = ReceiptStore::open(&root, 10, &validator()).unwrap();
    let sha = hash_file(&source).unwrap().0;
    let first = store
        .ingest(
            "machine-1",
            "authenticated-person",
            "upload-1",
            &source,
            &sha,
            at(101),
        )
        .unwrap();
    assert_eq!(
        first.session.as_deref(),
        Some("com.example.agent:install%3A7:run%3A7")
    );
    assert!(first.identity_mismatch.is_some());
    assert_eq!(first.status, "received");
    assert_eq!(
        fs::read(root.join(format!("objects/{sha}.jsonl"))).unwrap(),
        original
    );
    assert_eq!(first.byte_length, Some(original.len() as u64));
    assert_eq!(
        store
            .ingest(
                "machine-1",
                "authenticated-person",
                "upload-1",
                &source,
                &sha,
                at(102)
            )
            .unwrap()
            .received_at,
        first.received_at
    );
    let mut changed = original.clone();
    changed.extend_from_slice(
        b"{\"type\":\"message\",\"id\":\"new\",\"role\":\"user\",\"content\":[]}\n",
    );
    write(&source, &changed);
    let sha2 = hash_file(&source).unwrap().0;
    assert!(store
        .ingest(
            "machine-1",
            "authenticated-person",
            "upload-1",
            &source,
            &sha2,
            at(103)
        )
        .is_err());
    let second = store
        .ingest(
            "machine-1",
            "authenticated-person",
            "upload-2",
            &source,
            &sha2,
            at(104),
        )
        .unwrap();
    assert_eq!(second.replaces.unwrap()["sha256"], sha);
    // Reverting to an earlier digest is still a new receipt and replaces the current version.
    write(&source, &original);
    let third = store
        .ingest(
            "machine-1",
            "authenticated-person",
            "upload-3",
            &source,
            &sha,
            at(110),
        )
        .unwrap();
    assert_eq!(third.replaces.unwrap()["sha256"], sha2);
    store.rotate(at(131)).unwrap();
    drop(store);
    let mut store = ReceiptStore::open(&root, 10, &validator()).unwrap();
    store.rotate(at(140)).unwrap();
    let docs = check_manifests(&root);
    assert_eq!(docs.len(), 4);
    assert_eq!(docs[0]["entries"].as_array().unwrap().len(), 2);
    assert_eq!(docs[1]["entries"].as_array().unwrap().len(), 1);
    assert_eq!(docs[2]["entries"], json!([]));
    assert_eq!(docs[3]["entries"], json!([]));
    let files = manifests(&root);
    assert!(docs[0]["previousManifest"].is_null());
    for i in 1..docs.len() {
        assert_eq!(
            docs[i]["previousManifest"]["sha256"],
            hash_file(&files[i - 1]).unwrap().0
        );
    }
    assert!(store.heartbeat("machine-1", at(130)).is_err());
    assert!(ReceiptStore::open(&root, 20, &validator()).is_err());
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(
            fs::metadata(files[0].clone()).unwrap().permissions().mode() & 0o777,
            0o600
        );
    }
}

#[test]
fn unreadable_and_failed_receipts_keep_only_observed_facts() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path().join("store");
    let file = tmp.path().join("broken.jsonl");
    write(&file, b"broken\n");
    let sha = hash_file(&file).unwrap().0;
    let mut store = ReceiptStore::open(&root, 10, &validator()).unwrap();
    let unreadable = store
        .ingest("machine-1", "person", "broken", &file, &sha, at(201))
        .unwrap();
    assert_eq!(unreadable.status, "unreadable");
    assert!(unreadable.session.is_none());
    assert_eq!(
        fs::read(root.join(format!("objects/{sha}.bin"))).unwrap(),
        b"broken\n"
    );
    write(&file, &sample("good"));
    let mismatch = store
        .ingest(
            "machine-1",
            "person",
            "wrong-digest",
            &file,
            &"0".repeat(64),
            at(202),
        )
        .unwrap();
    assert_eq!(mismatch.status, "unreadable");
    assert_ne!(mismatch.sha256.unwrap(), "0".repeat(64));
    let failed = store
        .failure(
            "machine-1",
            "person",
            "failed",
            Failure {
                reason: "Source was unavailable.",
                session: None,
            },
            at(203),
        )
        .unwrap();
    assert_eq!(failed.status, "failed");
    assert!(failed.sha256.is_none());
    assert!(failed.byte_length.is_none());
    store.heartbeat("machine-2", at(201)).unwrap();
    store.rotate(at(211)).unwrap();
    let docs = check_manifests(&root);
    assert_eq!(docs.len(), 2);
    let received = docs.iter().find(|d| d["machine"] == "machine-1").unwrap();
    assert_eq!(received["entries"].as_array().unwrap().len(), 3);
    let failed = &received["entries"][2];
    assert!(failed.get("sha256").is_none());
}

fn args(root: &Path, source: &Path) -> CollectArgs {
    CollectArgs {
        target: root.join("target").to_string_lossy().into(),
        state: root.join("state"),
        machine: Some("machine-1".into()),
        uploader: Some("person".into()),
        sources: vec![format!("claude-code={}", source.display())],
        agents: Vec::new(),
        namespace: None,
        token_file: None,
        watch: false,
        poll_seconds: 1,
        poll_only: false,
        window_seconds: 1,
        recent_hours: None,
        max_sessions: None,
        max_record_bytes: 16 * 1024 * 1024,
    }
}
fn native(path: &Path, id: &str, uuid: &str, text: &str) {
    write(path,format!("{}\n",json!({"sessionId":id,"uuid":uuid,"type":"user","message":{"role":"user","content":text}})).as_bytes());
}
#[test]
fn collector_groups_sources_skips_unchanged_and_resumes_after_changes() {
    let tmp = tempfile::tempdir().unwrap();
    let input = tmp.path().join("input");
    fs::create_dir(&input).unwrap();
    native(&input.join("a.jsonl"), "session-a", "a", "first");
    native(&input.join("b.jsonl"), "session-a", "b", "second");
    native(&input.join("c.jsonl"), "session-b", "c", "other");
    let config = args(tmp.path(), &input);
    let first = collect(config.clone(), &validator()).unwrap();
    assert_eq!(first.uploaded_sessions, 2);
    assert_eq!(first.failures, 0);
    let unchanged = collect(config.clone(), &validator()).unwrap();
    assert_eq!(unchanged.converted_sessions, 0);
    assert_eq!(unchanged.unchanged_sessions, 2);
    native(&input.join("b.jsonl"), "session-a", "b", "changed");
    let changed = collect(config.clone(), &validator()).unwrap();
    assert_eq!(changed.converted_sessions, 1);
    assert_eq!(changed.uploaded_sessions, 1);
    let state: Value =
        serde_json::from_slice(&fs::read(config.state.join("state.json")).unwrap()).unwrap();
    let sha = state["sessions"]["claude-code:session-a"]["sha256"]
        .as_str()
        .unwrap();
    let file = tmp.path().join(format!("target/objects/{sha}.jsonl"));
    let content = fs::read_to_string(file).unwrap();
    assert!(content.contains("first"));
    assert!(content.contains("changed"));
    assert!(!content.contains("second"));
    fs::remove_file(input.join("a.jsonl")).unwrap();
    assert_eq!(
        collect(config.clone(), &validator())
            .unwrap()
            .uploaded_sessions,
        1
    );
    let mut wrong = config.clone();
    wrong.machine = Some("different-machine".into());
    assert!(collect(wrong, &validator()).is_err());
    let mut store = ReceiptStore::open(&tmp.path().join("target"), 1, &validator()).unwrap();
    store
        .rotate(Utc::now() + chrono::Duration::seconds(2))
        .unwrap();
    check_manifests(&tmp.path().join("target"));
}

struct RunningReceiver {
    url: String,
    stop: Arc<AtomicBool>,
    thread: Option<std::thread::JoinHandle<()>>,
}
impl Drop for RunningReceiver {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        self.thread.take().unwrap().join().unwrap();
    }
}
fn receiver(root: &Path, max: u64) -> RunningReceiver {
    let auth = root.join("auth.json");
    write(&auth,serde_json::to_string(&json!([{"token":"synthetic-local-bearer-token","uploader":"server-account","machines":["machine-1"]}])).unwrap().as_bytes());
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&auth, fs::Permissions::from_mode(0o600)).unwrap();
    }
    let mut server = Receiver::bind(
        ReceiveArgs {
            bind: "127.0.0.1:0".parse().unwrap(),
            out: root.join("receiver"),
            auth_file: auth,
            window_seconds: 1,
            max_upload_bytes: max,
        },
        validator(),
    )
    .unwrap();
    let url = format!("http://{}", server.address().unwrap());
    let stop = Arc::new(AtomicBool::new(false));
    let signal = stop.clone();
    let thread = std::thread::spawn(move || {
        while !signal.load(Ordering::Relaxed) {
            server.serve_once(Duration::from_millis(20)).unwrap();
        }
    });
    RunningReceiver {
        url,
        stop,
        thread: Some(thread),
    }
}
#[test]
fn receiver_authenticates_binds_machine_and_deduplicates_exact_uploads() {
    let tmp = tempfile::tempdir().unwrap();
    let server = receiver(tmp.path(), 4096);
    let client = reqwest::blocking::Client::builder()
        .no_proxy()
        .build()
        .unwrap();
    let url = format!("{}/v1/sessions", server.url);
    let bytes = sample("session");
    let file = tmp.path().join("session.jsonl");
    write(&file, &bytes);
    let sha = hash_file(&file).unwrap().0;
    assert_eq!(client.post(&url).send().unwrap().status(), 401);
    assert_eq!(
        client
            .post(&url)
            .bearer_auth("synthetic-local-bearer-token")
            .header("X-ASR-Machine", "wrong-machine")
            .send()
            .unwrap()
            .status(),
        403
    );
    for _ in 0..2 {
        let response = client
            .post(&url)
            .bearer_auth("synthetic-local-bearer-token")
            .header("X-ASR-Machine", "machine-1")
            .header("X-ASR-Upload-ID", "same-request")
            .header("X-ASR-Sha256", &sha)
            .body(bytes.clone())
            .send()
            .unwrap();
        assert_eq!(response.status(), 200);
        let receipt: Value = response.json().unwrap();
        assert_eq!(receipt["uploader"], "server-account");
        assert_eq!(receipt["sha256"], sha);
        assert!(receipt["identityMismatch"].is_object());
    }
    let too_big = client
        .post(&url)
        .bearer_auth("synthetic-local-bearer-token")
        .header("X-ASR-Machine", "machine-1")
        .header("X-ASR-Upload-ID", "too-big")
        .header("X-ASR-Sha256", &sha)
        .body(vec![b'x'; 4097])
        .send()
        .unwrap();
    assert_eq!(too_big.status(), 413);
    drop(server);
    let mut store = ReceiptStore::open(&tmp.path().join("receiver"), 1, &validator()).unwrap();
    store
        .rotate(Utc::now() + chrono::Duration::seconds(2))
        .unwrap();
    let docs = check_manifests(&tmp.path().join("receiver"));
    let entries: Vec<_> = docs
        .iter()
        .flat_map(|d| d["entries"].as_array().unwrap())
        .collect();
    assert_eq!(
        entries.iter().filter(|e| e["status"] == "received").count(),
        1
    );
    assert_eq!(
        entries.iter().filter(|e| e["status"] == "failed").count(),
        1
    );
}

#[test]
fn collector_http_target_uses_server_identity() {
    let tmp = tempfile::tempdir().unwrap();
    let server = receiver(tmp.path(), 1024 * 1024);
    let input = tmp.path().join("native.jsonl");
    native(&input, "session", "item", "synthetic prompt");
    let token = tmp.path().join("token");
    let mut file = tempfile::NamedTempFile::new_in(tmp.path()).unwrap();
    file.write_all(b"synthetic-local-bearer-token\n").unwrap();
    file.persist(&token).unwrap();
    let mut config = args(tmp.path(), &input);
    config.target = server.url.clone();
    config.token_file = Some(token);
    config.uploader = None;
    assert_eq!(
        collect(config.clone(), &validator())
            .unwrap()
            .uploaded_sessions,
        1
    );
    assert_eq!(collect(config, &validator()).unwrap().unchanged_sessions, 1);
}

#[test]
fn collector_reuses_pending_upload_after_lost_acknowledgement() {
    let tmp = tempfile::tempdir().unwrap();
    let input = tmp.path().join("native.jsonl");
    native(&input, "session", "item", "synthetic retry");
    let config = args(tmp.path(), &input);
    assert_eq!(
        collect(config.clone(), &validator())
            .unwrap()
            .uploaded_sessions,
        1
    );
    let db = rusqlite::Connection::open(tmp.path().join("target/receipts.sqlite3")).unwrap();
    let request: String = db
        .query_row("SELECT request FROM receipts", [], |r| r.get(0))
        .unwrap();
    let state_file = config.state.join("state.json");
    let mut state: Value = serde_json::from_slice(&fs::read(&state_file).unwrap()).unwrap();
    let saved = state["sessions"]
        .as_object_mut()
        .unwrap()
        .remove("claude-code:session")
        .unwrap();
    state["pending"]["claude-code:session"] =
        json!({"signature":saved["signature"],"sha256":saved["sha256"],"request":request});
    fs::write(&state_file, serde_json::to_vec(&state).unwrap()).unwrap();
    assert_eq!(
        collect(config.clone(), &validator())
            .unwrap()
            .uploaded_sessions,
        1
    );
    let count: u64 = db
        .query_row("SELECT COUNT(*) FROM receipts", [], |r| r.get(0))
        .unwrap();
    assert_eq!(count, 1);
    let state: Value = serde_json::from_slice(&fs::read(&state_file).unwrap()).unwrap();
    assert!(state["pending"].as_object().unwrap().is_empty());
    assert!(state["sessions"]["claude-code:session"].is_object());
}

#[test]
fn receiver_reports_partial_http_body_without_inventing_a_digest() {
    use std::io::Read;
    let tmp = tempfile::tempdir().unwrap();
    let server = receiver(tmp.path(), 4096);
    let address = server.url.strip_prefix("http://").unwrap();
    let mut connection = std::net::TcpStream::connect(address).unwrap();
    connection
        .set_read_timeout(Some(Duration::from_secs(5)))
        .unwrap();
    let token = "synthetic-local-bearer-token";
    let request = format!("POST /v1/sessions HTTP/1.1\r\nHost: {address}\r\nAuthorization: Bearer {token}\r\nX-ASR-Machine: machine-1\r\nX-ASR-Upload-ID: partial-body\r\nX-ASR-Sha256: {}\r\nContent-Length: 4096\r\nConnection: close\r\n\r\nhalf", "0".repeat(64));
    connection.write_all(request.as_bytes()).unwrap();
    connection.shutdown(std::net::Shutdown::Write).unwrap();
    let mut response = String::new();
    connection.read_to_string(&mut response).unwrap();
    assert!(response.starts_with("HTTP/1.1 400"), "{response:?}");
    drop(server);
    let mut store = ReceiptStore::open(&tmp.path().join("receiver"), 1, &validator()).unwrap();
    store
        .rotate(Utc::now() + chrono::Duration::seconds(2))
        .unwrap();
    let docs = check_manifests(&tmp.path().join("receiver"));
    let entries: Vec<_> = docs
        .iter()
        .flat_map(|d| d["entries"].as_array().unwrap())
        .collect();
    assert_eq!(entries.len(), 1);
    assert_eq!(entries[0]["status"], "failed");
    assert!(entries[0].get("sha256").is_none());
    assert!(entries[0].get("byteLength").is_none());
}

fn copy_native(source: &Path, out: &Path) {
    fs::create_dir_all(out).unwrap();
    for entry in fs::read_dir(source).unwrap() {
        let entry = entry.unwrap();
        let target = out.join(entry.file_name());
        if entry.path().is_dir() {
            copy_native(&entry.path(), &target);
        } else {
            fs::copy(entry.path(), target).unwrap();
        }
    }
}
fn native_fixture(agent: asr_convert::Agent, root: &Path) -> PathBuf {
    use asr_convert::Agent;
    let fixtures = repo().join("crates/asr-convert/tests/fixtures");
    let input = root.join("input");
    fs::create_dir_all(&input).unwrap();
    let sql = fixtures.join(format!("sqlite/{}.sql", agent.name()));
    if sql.is_file() {
        rusqlite::Connection::open(input.join("native.db"))
            .unwrap()
            .execute_batch(&fs::read_to_string(sql).unwrap())
            .unwrap();
    } else {
        let source = ["w1-conv-a", "jsonl-b", "documents"]
            .into_iter()
            .map(|batch| fixtures.join(batch).join(agent.name()))
            .find(|p| p.is_dir())
            .unwrap_or_else(|| repo().join(format!("samples/{}/native", agent.name())));
        copy_native(&source, &input);
        let create = |script: &str, name: &str| {
            let path = input.join(name);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            rusqlite::Connection::open(path)
                .unwrap()
                .execute_batch(&fs::read_to_string(input.join(script)).unwrap())
                .unwrap();
        };
        if agent == Agent::Hermes {
            create("state.sql", "state.db");
        }
        if agent == Agent::NanoClaw {
            create("inventory.sql", "data/v2.db");
            create(
                "inbound.sql",
                "data/v2-sessions/group-sample/nano-sample/inbound.db",
            );
            create(
                "outbound.sql",
                "data/v2-sessions/group-sample/nano-sample/outbound.db",
            );
        }
    }
    input
}

#[test]
fn collection_uses_every_converter_and_preserves_offline_bytes() {
    use asr_convert::{convert, Agent, Options};
    for agent in Agent::ALL {
        let temporary = tempfile::tempdir().unwrap();
        let input = native_fixture(agent, temporary.path());
        let mut options = Options::new(agent, input.clone(), temporary.path().join("offline"));
        if agent == Agent::Goose {
            options.namespace = Some("synthetic-installation".into());
        }
        let expected = convert(&options).unwrap();
        assert!(expected.sessions > 0, "{}", agent.name());
        let mut collect_args = args(temporary.path(), &input);
        collect_args.window_seconds = 3600;
        collect_args.sources = vec![format!("{}={}", agent.name(), input.display())];
        collect_args.namespace = options.namespace.clone();
        let first = collect(collect_args.clone(), &validator()).unwrap();
        assert_eq!(
            first.failures,
            0,
            "{}: {:?}",
            agent.name(),
            first.diagnostics
        );
        assert_eq!(
            first.uploaded_sessions,
            expected.sessions,
            "{}",
            agent.name()
        );
        for entry in fs::read_dir(&options.out).unwrap() {
            let path = entry.unwrap().path();
            if path.extension().is_some_and(|s| s == "jsonl") {
                let contents = fs::read_to_string(&path).unwrap();
                let header: Value = serde_json::from_str(contents.lines().next().unwrap()).unwrap();
                let reference = asr_core::identity::session_ref(
                    agent.name(),
                    header["namespace"].as_str(),
                    header["sessionId"].as_str().unwrap(),
                );
                let state: Value = serde_json::from_slice(
                    &fs::read(temporary.path().join("state/state.json")).unwrap(),
                )
                .unwrap();
                assert!(
                    state["sessions"].get(&reference).is_some(),
                    "{} checkpoint identity",
                    agent.name()
                );
                let sha = hash_file(&path).unwrap().0;
                assert_eq!(
                    fs::read(temporary.path().join(format!("target/objects/{sha}.jsonl"))).unwrap(),
                    fs::read(path).unwrap(),
                    "{}",
                    agent.name()
                );
            }
        }
        let again = collect(collect_args, &validator()).unwrap();
        assert_eq!(again.failures, 0, "{}", agent.name());
        assert_eq!(again.converted_sessions, 0, "{}", agent.name());
        assert_eq!(
            again.unchanged_sessions,
            expected.sessions,
            "{}",
            agent.name()
        );
    }
}

#[test]
fn multiple_database_sessions_and_wal_changes_are_collected() {
    use asr_convert::Agent;
    let temporary = tempfile::tempdir().unwrap();
    let input = native_fixture(Agent::Crush, temporary.path());
    let db = rusqlite::Connection::open(input.join("native.db")).unwrap();
    db.execute_batch("PRAGMA journal_mode=WAL; PRAGMA wal_autocheckpoint=0; INSERT INTO sessions(id,title) VALUES('second','Second synthetic session');").unwrap();
    let mut collect_args = args(temporary.path(), &input);
    collect_args.window_seconds = 3600;
    collect_args.sources = vec![format!("crush={}", input.display())];
    let first = collect(collect_args.clone(), &validator()).unwrap();
    assert_eq!(first.failures, 0);
    assert_eq!(first.uploaded_sessions, 2);
    let again = collect(collect_args.clone(), &validator()).unwrap();
    assert_eq!(again.converted_sessions, 0);
    db.execute(
        "UPDATE sessions SET title='Changed in WAL' WHERE id='second'",
        [],
    )
    .unwrap();
    let changed = collect(collect_args, &validator()).unwrap();
    assert_eq!(changed.failures, 0);
    assert_eq!(changed.converted_sessions, 2);
    assert_eq!(changed.uploaded_sessions, 1);
}

#[test]
fn companion_metadata_changes_trigger_collection() {
    use asr_convert::Agent;
    let temporary = tempfile::tempdir().unwrap();
    let input = native_fixture(Agent::MistralVibe, temporary.path());
    let mut collect_args = args(temporary.path(), &input);
    collect_args.window_seconds = 3600;
    collect_args.sources = vec![format!("mistral-vibe={}", input.display())];
    assert_eq!(
        collect(collect_args.clone(), &validator())
            .unwrap()
            .uploaded_sessions,
        1
    );
    let path = input.join("meta.json");
    let mut meta: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    meta["title"] = json!("Changed companion metadata");
    fs::write(path, serde_json::to_vec(&meta).unwrap()).unwrap();
    let changed = collect(collect_args, &validator()).unwrap();
    assert_eq!(changed.failures, 0);
    assert_eq!(changed.uploaded_sessions, 1);
}

fn failure_rows(store: &Path) -> Vec<Value> {
    let db = rusqlite::Connection::open(store.join("receipts.sqlite3")).unwrap();
    let rows = db.prepare(
        "SELECT entry FROM receipts WHERE json_extract(entry, '$.status')='failed' ORDER BY seq",
    )
    .unwrap()
    .query_map([], |r| r.get::<_, String>(0))
    .unwrap()
    .map(|r| serde_json::from_str(&r.unwrap()).unwrap())
    .collect();
    rows
}

#[test]
fn collector_records_one_named_failure_per_version_across_restarts_and_reversions() {
    let tmp = tempfile::tempdir().unwrap();
    let input = tmp.path().join("native.jsonl");
    native(&input, "session:failure", "a", "version one");
    // Simulate a validator that cannot accept a converted stream. This remains
    // independent of converter recovery for malformed native record shapes.
    let unavailable = tmp.path().join("unavailable-validator.cjs");
    write(&unavailable, b"process.exit(1);\n");
    let mut config = args(tmp.path(), &input);
    config.window_seconds = 3600;
    for _ in 0..3 {
        let summary = collect(config.clone(), &unavailable).unwrap();
        assert_eq!(summary.failures, 1);
        assert_eq!(summary.uploaded_sessions, 0);
    }
    let target = tmp.path().join("target");
    let first = failure_rows(&target);
    assert_eq!(first.len(), 1);
    assert_eq!(first[0]["session"], "claude-code:session%3Afailure");
    assert!(first[0].get("sha256").is_none());
    native(&input, "session:failure", "a", "version two");
    assert_eq!(collect(config.clone(), &unavailable).unwrap().failures, 1);
    assert_eq!(failure_rows(&target).len(), 2);
    native(&input, "session:failure", "a", "version one");
    assert_eq!(collect(config.clone(), &unavailable).unwrap().failures, 1);
    assert_eq!(failure_rows(&target).len(), 2);
    assert_eq!(
        failure_rows(&target)[0]["receivedAt"],
        first[0]["receivedAt"]
    );
    // Transient failures are retried. The same version can later succeed.
    assert_eq!(collect(config, &validator()).unwrap().uploaded_sessions, 1);
    let mut store = ReceiptStore::open(&target, 3600, &validator()).unwrap();
    store
        .rotate(Utc::now() + chrono::Duration::hours(1))
        .unwrap();
    let docs = check_manifests(&target);
    assert_eq!(
        docs.iter()
            .flat_map(|d| d["entries"].as_array().unwrap())
            .filter(|e| e["status"] == "failed")
            .count(),
        2
    );
}

#[test]
fn receiver_preserves_failure_sessions_and_rejects_invalid_or_reused_identity() {
    let tmp = tempfile::tempdir().unwrap();
    let server = receiver(tmp.path(), 4096);
    let client = reqwest::blocking::Client::builder()
        .no_proxy()
        .build()
        .unwrap();
    let post = |id: &str, session: Value| {
        client
            .post(format!("{}/v1/failures", server.url))
            .bearer_auth("synthetic-local-bearer-token")
            .header("X-ASR-Machine", "machine-1")
            .header("X-ASR-Upload-ID", id)
            .json(&json!({"reason":"Conversion failed.", "session": session}))
            .send()
            .unwrap()
    };
    let session = json!("codex:install%3A7:failed");
    let first = post("named-failure", session.clone());
    assert_eq!(first.status(), 200);
    let receipt: Value = first.json().unwrap();
    assert_eq!(receipt["session"], session);
    assert_eq!(
        post("named-failure", session).json::<Value>().unwrap(),
        receipt
    );
    assert_eq!(
        post("named-failure", json!("codex:different")).status(),
        400
    );
    assert_eq!(post("invalid", json!("codex:bad#record")).status(), 400);
    assert_eq!(post("invalid-type", json!(17)).status(), 400);
    assert_eq!(post("unnamed", Value::Null).status(), 200);
    drop(server);
    assert_eq!(failure_rows(&tmp.path().join("receiver")).len(), 2);
}
