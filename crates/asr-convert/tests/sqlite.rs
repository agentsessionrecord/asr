//! Authored storage examples and source-semantic regressions, never real history.
use asr_convert::{convert, Agent, Options};
use rusqlite::{params, Connection};
use serde_json::{json, Value};
use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
};
fn fixture(agent: Agent) -> (tempfile::TempDir, Options, Connection) {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("native.db");
    let db = Connection::open(&path).unwrap();
    let file = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join(format!("tests/fixtures/sqlite/{}.sql", agent.name()));
    db.execute_batch(&fs::read_to_string(file).unwrap())
        .unwrap();
    let mut o = Options::new(agent, path, temp.path().join("out"));
    if agent == Agent::Goose {
        o.namespace = Some("example-installation".into());
    }
    (temp, o, db)
}
fn output(o: &Options) -> PathBuf {
    fs::read_dir(&o.out)
        .unwrap()
        .map(|e| e.unwrap().path())
        .find(|p| p.extension().is_some_and(|s| s == "jsonl"))
        .unwrap()
}
fn records(o: &Options) -> Vec<Value> {
    fs::read_to_string(output(o))
        .unwrap()
        .lines()
        .map(|s| asr_core::jsonl::decode(s).unwrap())
        .collect()
}
fn validate(o: &Options) {
    let r = Command::new("node")
        .arg(
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tools/validator/bin/asr-validate.js"),
        )
        .args(["--json"])
        .arg(&o.out)
        .output()
        .unwrap();
    assert!(r.status.success(), "{}", String::from_utf8_lossy(&r.stdout));
}
fn run(o: &Options) -> Vec<Value> {
    convert(o).unwrap();
    validate(o);
    records(o)
}
fn record<'a>(rows: &'a [Value], kind: &str) -> &'a Value {
    rows.iter().find(|r| r["type"] == kind).unwrap()
}
#[test]
fn database_goldens_validate_and_survive_relocation() {
    for agent in Agent::ALL.into_iter().filter(|a| {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join(format!("tests/fixtures/sqlite/{}.sql", a.name()))
            .exists()
    }) {
        let (_temp, mut o, db) = fixture(agent);
        let summary = convert(&o).unwrap();
        assert_eq!(summary.sessions, 1, "{}", agent.name());
        validate(&o);
        let bytes = fs::read(output(&o)).unwrap();
        let golden = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join(format!("tests/golden/{}.jsonl", agent.name()));
        if std::env::var_os("UPDATE_SQLITE_GOLDENS").is_some() {
            fs::write(&golden, &bytes).unwrap();
        }
        assert_eq!(bytes, fs::read(golden).unwrap(), "{}", agent.name());
        drop(db);
        let moved = o.input.with_file_name("relocated.sqlite");
        fs::rename(&o.input, &moved).unwrap();
        o.input = moved;
        convert(&o).unwrap();
        assert_eq!(
            bytes,
            fs::read(output(&o)).unwrap(),
            "{} relocation",
            agent.name()
        );
    }
}
#[test]
fn sqlite_reads_wal_and_recovers_bounded_corrupt_rows() {
    let (_d, mut o, db) = fixture(Agent::Crush);
    db.execute_batch("PRAGMA journal_mode=WAL; PRAGMA wal_checkpoint(TRUNCATE);")
        .unwrap();
    db.execute("UPDATE messages SET parts='not-json' WHERE id='prompt'", [])
        .unwrap();
    let summary = convert(&o).unwrap();
    assert_eq!(summary.diagnostics["unparseable_source_row"], 1);
    let rows = records(&o);
    assert!(rows.iter().any(|v| v["type"] == "gap"));
    assert!(rows.iter().any(|v| v["id"] == "reply"));
    validate(&o);
    db.execute(
        "UPDATE messages SET parts=?1 WHERE id='prompt'",
        [json!([{"type":"text","data":{"text":"x".repeat(4096)}}]).to_string()],
    )
    .unwrap();
    o.max_record_bytes = 1024;
    let summary = convert(&o).unwrap();
    assert_eq!(summary.diagnostics["oversized_source_row"], 1);
    validate(&o);
    assert!(!fs::read_dir(&o.out).unwrap().any(|e| e
        .unwrap()
        .file_name()
        .to_string_lossy()
        .starts_with(".asr-stage-")));
}
#[test]
fn namespace_required_for_goose_and_directory_keyed_kiro() {
    let (_d, mut o, _db) = fixture(Agent::Goose);
    o.namespace = None;
    assert!(convert(&o).unwrap_err().to_string().contains("namespace"));
    let (_d, mut o, db) = fixture(Agent::Kiro);
    db.execute_batch("ALTER TABLE conversations_v2 RENAME TO conversations; UPDATE conversations SET conversation_id=NULL;").unwrap();
    assert!(convert(&o).unwrap_err().to_string().contains("namespace"));
    o.namespace = Some("profile:one".into());
    let rows = run(&o);
    assert_eq!(rows[0]["sessionId"], "/work/app");
    assert_eq!(rows[0]["namespace"], "profile:one");
}
#[test]
fn collision_and_file_aliases_do_not_merge_stores() {
    let (temp, mut o, db) = fixture(Agent::AstrBot);
    drop(db);
    let sources = temp.path().join("sources");
    fs::create_dir(&sources).unwrap();
    let native = sources.join("native.db");
    fs::rename(&o.input, &native).unwrap();
    let copy = sources.join("copy.db");
    fs::copy(&native, &copy).unwrap();
    let extra = Connection::open(&native).unwrap();
    extra
        .execute(
            "INSERT INTO conversations VALUES(43,'good','[]','Independent',0)",
            [],
        )
        .unwrap();
    drop(extra);
    o.input = sources.clone();
    let summary = convert(&o).unwrap();
    assert_eq!(summary.sessions, 1);
    assert_eq!(
        summary.session_diagnostics["astrbot:example"]["colliding_session_identity"],
        1
    );
    fs::remove_file(copy).unwrap();
    #[cfg(unix)]
    {
        std::os::unix::fs::symlink(sources.join("native.db"), sources.join("alias.db")).unwrap();
    }
    assert_eq!(convert(&o).unwrap().sessions, 2);
}
#[test]
fn source_facts_and_summary_losses_remain_conservative() {
    let (_d, o, _db) = fixture(Agent::Crush);
    let r = run(&o);
    assert_eq!(record(&r, "tool_call")["input"]["n"], "9007199254740993");
    assert_eq!(record(&r, "tool_result")["status"], "completed");
    assert!(!r.iter().any(|v| v["type"] == "inference"));
    let (_d, o, _db) = fixture(Agent::Lingma);
    let r = run(&o);
    let summary = r.iter().find(|v| v["role"] == "assistant").unwrap();
    assert_eq!(summary["truncated"], true);
    assert!(summary.get("ts").is_none());
    assert!(summary.get("author").is_none());
    let (_d, o, _db) = fixture(Agent::AstrBot);
    let r = run(&o);
    assert!(!r
        .iter()
        .any(|v| v["type"] == "session_info" && v.get("usage").is_some()));
    assert!(!record(&r, "message").get("author").is_some());
    let (_d, o, _db) = fixture(Agent::Shelley);
    let r = run(&o);
    assert_eq!(record(&r, "inference")["usage"]["inputTokens"], 13);
    assert_eq!(record(&r, "inference")["cost"]["amount"], 0.0);
    let (_d, o, _db) = fixture(Agent::OpenClaw);
    let r = run(&o);
    let inf = record(&r, "inference");
    assert_eq!(inf["model"]["requested"], "requested-model");
    assert_eq!(inf["model"]["id"], "served-model");
    assert_eq!(inf["usage"]["inputTokens"], 12);
    assert!(r[0].get("endedAt").is_none());
}
#[test]
fn opencode_usage_folding_and_denial_snapshot() {
    let (_d, o, db) = fixture(Agent::OpenCode);
    db.execute("INSERT INTO part VALUES('p4','assistant','example',?1)",[json!({"type":"step-finish","tokens":{"input":10,"output":5,"reasoning":3,"cache":{"read":2}},"cost":0,"reason":"stop"}).to_string()]).unwrap();
    db.execute("UPDATE part SET data=?1 WHERE id='p3'",[json!({"type":"tool","callID":"edit-1","tool":"edit","state":{"status":"error","input":{},"error":{"type":"aborted","message":"The user declined this tool call"}}}).to_string()]).unwrap();
    let r = run(&o);
    let inf = record(&r, "inference");
    assert_eq!(inf["usage"]["inputTokens"], 12);
    assert_eq!(inf["usage"]["outputTokens"], 8);
    assert_eq!(inf["model"]["requested"], "requested-model");
    assert!(inf["model"].get("id").is_none());
    assert!(record(&r, "tool_call").get("inferenceId").is_none());
    assert!(!r.iter().any(|v| v["type"] == "approval"));
    assert_eq!(
        record(&r, "tool_result")["error"]["message"],
        "The user declined this tool call"
    );
    let message = r.iter().position(|v| v["id"] == "assistant").unwrap();
    let head = r
        .iter()
        .position(|v| {
            v["type"] == "ai.opencode/event"
                && v["_meta"]["ai.opencode"]["native"]["table"] == "message"
                && v["_meta"]["ai.opencode"]["native"]["data"]["id"] == "assistant"
        })
        .unwrap();
    assert!(head < message);
}
#[test]
fn decoded_secrets_are_removed_across_all_projection_and_vendor_records() {
    let secret = concat!("synthetic-", "secret-value");
    let (_d, o, db) = fixture(Agent::Goose);
    for (id, part) in [
        (
            4,
            json!({"type":"actionRequired","data":{"actionType":"elicitation","id":"request","requested_schema":{"properties":{"answer":{"type":"string","format":"password"}}}}}),
        ),
        (
            5,
            json!({"type":"actionRequired","data":{"actionType":"elicitationResponse","id":"request","action":"accept","user_data":{"answer":secret}}}),
        ),
        (6, json!({"type":"text","text":format!("echo {secret}")})),
    ] {
        db.execute(
            "INSERT INTO messages VALUES(?1,?2,'example','user',?3,?1,'{}')",
            params![id, id.to_string(), json!([part]).to_string()],
        )
        .unwrap();
    }
    let r = run(&o);
    assert!(!serde_json::to_string(&r).unwrap().contains(secret));
    assert!(r[0]["missing"]
        .as_array()
        .unwrap()
        .contains(&json!("redacted_content")));
    let (_d, o, db) = fixture(Agent::AstrBot);
    db.execute("UPDATE conversations SET content=?1",[json!([{"role":"user","api_key":secret,"content":format!("before {secret}"),"signature":"opaque-state"}]).to_string()]).unwrap();
    let r = run(&o);
    let text = serde_json::to_string(&r).unwrap();
    assert!(!text.contains(secret));
    assert!(!text.contains("opaque-state"));
}
#[test]
fn compressed_snapshots_and_exact_messagepack_counts_validate() {
    let (_d, o, db) = fixture(Agent::Zed);
    let raw: Vec<u8> = db
        .query_row("SELECT data FROM threads", [], |r| r.get(0))
        .unwrap();
    let bytes = zstd::encode_all(raw.as_slice(), 1).unwrap();
    db.execute("UPDATE threads SET data=?1,data_type='zstd'", [bytes])
        .unwrap();
    let r = run(&o);
    assert_eq!(record(&r, "message")["id"], "prompt");
    let (_d, o, _db) = fixture(Agent::DeepAgents);
    let r = run(&o);
    assert_eq!(r.iter().filter(|v| v["type"] == "message").count(), 2);
    assert_eq!(record(&r, "inference")["usage"]["inputTokens"], 10);
    assert!(!r
        .iter()
        .any(|v| v["type"] == "message" && v["content"].to_string().contains("Checkpoint-only")));
}
#[test]
fn native_calls_with_reused_ids_stay_ambiguous() {
    let (_d, o, db) = fixture(Agent::Crush);
    db.execute("UPDATE messages SET parts=?1 WHERE id='assistant'",[json!([{"type":"tool_call","data":{"id":"read-1","name":"read","input":"{}"}},{"type":"tool_call","data":{"id":"read-1","name":"other","input":"{}"}}]).to_string()]).unwrap();
    let r = run(&o);
    assert_eq!(
        r.iter()
            .filter(|r| r["type"] == "tool_call" && r["callId"] == "read-1")
            .count(),
        2
    );
}

#[test]
fn separate_results_are_preserved_without_inventing_a_pair() {
    let (_d, o, db) = fixture(Agent::Crush);
    db.execute("INSERT INTO messages VALUES('another','example','tool',?1,4000,NULL,0)",[json!([{"type":"tool_result","data":{"tool_call_id":"read-1","content":"different receipt","is_error":true}}]).to_string()]).unwrap();
    let r = run(&o);
    let results: Vec<_> = r.iter().filter(|r| r["type"] == "tool_result").collect();
    assert_eq!(results.len(), 2);
    assert!(results.iter().all(|r| r.get("callId").is_none()));
    assert!(results
        .iter()
        .all(|r| r["_meta"]["sh.charm.crush"]["nativeCallId"] == "read-1"));
}

#[test]
fn fallback_usage_and_unknown_cache_inclusion_stay_distinct() {
    let (_d, o, _db) = fixture(Agent::OpenCode);
    let r = run(&o);
    assert_eq!(r.iter().filter(|r| r["type"] == "inference").count(), 1);
    assert_eq!(record(&r, "inference")["usage"]["inputTokens"], 12);
    let (_d, o, _db) = fixture(Agent::Goose);
    let r = run(&o);
    let u = &record(&r, "inference")["usage"];
    assert!(u.get("inputTokens").is_none());
    assert_eq!(u["outputTokens"], 3);
    assert_eq!(u["cacheReadTokens"], 2);
    let (_d, o, db) = fixture(Agent::ForgeCode);
    let raw: String = db
        .query_row("SELECT context FROM conversations", [], |r| r.get(0))
        .unwrap();
    let mut raw: Value = serde_json::from_str(&raw).unwrap();
    raw["messages"][1]["usage"] = json!({"prompt_tokens":{"Actual":10},"completion_tokens":{"Actual":3},"cached_tokens":{"Actual":2}});
    db.execute("UPDATE conversations SET context=?1", [raw.to_string()])
        .unwrap();
    let r = run(&o);
    assert_eq!(record(&r, "tool_call")["callId"], "read-1");
    let u = &record(&r, "inference")["usage"];
    assert!(u.get("inputTokens").is_none());
    assert_eq!(u["outputTokens"], 3);
}

#[test]
fn openclaw_revisions_and_positioned_approvals_validate() {
    let (_d, o, db) = fixture(Agent::OpenClaw);
    db.execute_batch("DROP TABLE operator_approvals; CREATE TABLE operator_approvals(approval_id TEXT,status TEXT,decision TEXT,source_session_id TEXT,resolved_at_ms INTEGER,resolver_kind TEXT,terminal_reason TEXT); INSERT INTO operator_approvals VALUES('approval-one','allowed','allow-once','example',1000,'device',NULL),('unpositioned','denied','deny','example',1000,'device',NULL),('pending','pending','deny','example',NULL,NULL,NULL);").unwrap();
    let raw: String = db
        .query_row(
            "SELECT event_json FROM transcript_events WHERE seq=4",
            [],
            |r| r.get(0),
        )
        .unwrap();
    let mut event: Value = serde_json::from_str(&raw).unwrap();
    event["message"]["details"] = json!({"approvalId":"approval-one"});
    db.execute(
        "UPDATE transcript_events SET event_json=?1 WHERE seq=4",
        [event.to_string()],
    )
    .unwrap();
    let mut revised: Value = serde_json::from_str(
        &db.query_row::<String, _, _>(
            "SELECT event_json FROM transcript_events WHERE seq=3",
            [],
            |r| r.get(0),
        )
        .unwrap(),
    )
    .unwrap();
    revised["id"] = json!("revised");
    revised["supersedesEntryId"] = json!("assistant");
    revised["message"]["content"][0]["text"] = json!("Revised answer.");
    revised["message"]["usage"]["output"] = json!(5);
    db.execute(
        "INSERT INTO transcript_events VALUES('example',5,?1,NULL,NULL)",
        [revised.to_string()],
    )
    .unwrap();
    let r = run(&o);
    let a = r.iter().position(|r| r["type"] == "approval").unwrap();
    assert_eq!(r[a]["decision"], "approved");
    assert_eq!(r[a]["scope"], "once");
    assert!(r[a].get("by").is_none());
    assert_eq!(r[a + 1]["type"], "tool_result");
    assert_eq!(r[a + 1]["approvalId"], r[a]["id"]);
    assert_eq!(r.iter().filter(|r| r["type"] == "approval").count(), 1);
    assert_eq!(r.iter().filter(|r| r["type"] == "inference").count(), 1);
    assert_eq!(record(&r, "inference")["usage"]["outputTokens"], 5);
    assert_eq!(
        r.iter()
            .filter(|r| r["type"] == "message" && r["role"] == "assistant")
            .count(),
        1
    );
}

#[test]
fn openclaw_edit_requests_need_changed_receipts() {
    let (_d, o, db) = fixture(Agent::OpenClaw);
    let raw: String = db
        .query_row(
            "SELECT event_json FROM transcript_events WHERE seq=3",
            [],
            |r| r.get(0),
        )
        .unwrap();
    let mut event: Value = serde_json::from_str(&raw).unwrap();
    event["message"]["content"][1]["name"] = json!("write");
    event["message"]["content"][1]["arguments"] = json!({"path":"new.txt","content":"proposed"});
    db.execute(
        "UPDATE transcript_events SET event_json=?1 WHERE seq=3",
        [event.to_string()],
    )
    .unwrap();
    let r = run(&o);
    assert!(!r.iter().any(|r| r["type"] == "file_change"));
    let raw: String = db
        .query_row(
            "SELECT event_json FROM transcript_events WHERE seq=4",
            [],
            |r| r.get(0),
        )
        .unwrap();
    let mut event: Value = serde_json::from_str(&raw).unwrap();
    event["message"]["details"] = json!({"changed":true,"created":true});
    db.execute(
        "UPDATE transcript_events SET event_json=?1 WHERE seq=4",
        [event.to_string()],
    )
    .unwrap();
    let r = run(&o);
    let change = record(&r, "file_change");
    assert_eq!(change["status"], "applied");
    assert_eq!(change["op"], "add");
    assert_eq!(change["path"], "/work/app/new.txt");
    assert!(change.get("after").is_none());
}

#[test]
fn unknown_database_blobs_are_not_preserved_as_encoded_secrets() {
    let (_d, o, db) = fixture(Agent::Crush);
    let bytes = b"synthetic-private-blob";
    db.execute("UPDATE files SET content=?1", [bytes.as_slice()])
        .unwrap();
    let summary = convert(&o).unwrap();
    validate(&o);
    assert_eq!(summary.diagnostics["unsupported_binary_fields"], 1);
    let encoded = fs::read_to_string(output(&o)).unwrap();
    assert!(!encoded.contains("c3ludGhldGljLXByaXZhdGUtYmxvYg=="));
    assert!(!encoded.contains("synthetic-private-blob"));
    assert!(encoded.contains("native_binary_fields"));
}

#[test]
fn opencode_sequenced_migrations_do_not_duplicate_legacy_messages() {
    let (_d, o, db) = fixture(Agent::OpenCode);
    db.execute_batch("CREATE TABLE session_v2 AS SELECT * FROM session; CREATE TABLE session_message(id TEXT,session_id TEXT,seq INTEGER,type TEXT,data TEXT); INSERT INTO session_message VALUES('assistant','example',1,'assistant','{\"type\":\"ignored-native-label\",\"content\":[{\"type\":\"text\",\"text\":\"Current representation.\"}],\"tokens\":{\"input\":2,\"output\":1}}'); INSERT INTO part VALUES('orphan','absent','example','{\"type\":\"text\",\"text\":\"Unowned part.\"}');").unwrap();
    let r = run(&o);
    assert_eq!(
        r.iter()
            .filter(|r| r["type"] == "message" && r["id"] == "assistant")
            .count(),
        1
    );
    let m = r
        .iter()
        .find(|r| r["type"] == "message" && r["id"] == "assistant")
        .unwrap();
    assert_eq!(m["content"][0]["text"], "Current representation.");
    assert!(r
        .iter()
        .any(|r| r["_meta"]["ai.opencode"]["native"]["table"] == "orphan_part"));
    assert!(r
        .iter()
        .any(|r| r["_meta"]["ai.opencode"]["native"]["table"] == "legacy"));
}

#[test]
fn openclaw_database_precedes_plain_and_compressed_migration_archives() {
    let temporary = tempfile::tempdir().unwrap();
    let input = temporary.path().join("input");
    let agent = input.join("agents/example");
    fs::create_dir_all(agent.join("agent")).unwrap();
    fs::create_dir_all(agent.join("sessions")).unwrap();
    let fixtures = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures");
    Connection::open(agent.join("agent/openclaw-agent.sqlite"))
        .unwrap()
        .execute_batch(&fs::read_to_string(fixtures.join("sqlite/openclaw.sql")).unwrap())
        .unwrap();
    let archive = fs::read(fixtures.join("jsonl-b/openclaw/session.jsonl")).unwrap();
    fs::write(agent.join("sessions/plain.jsonl"), &archive).unwrap();
    fs::write(
        agent.join("sessions/compressed.jsonl.zst"),
        zstd::stream::encode_all(archive.as_slice(), 1).unwrap(),
    )
    .unwrap();
    let o = Options::new(Agent::OpenClaw, input, temporary.path().join("out"));
    assert_eq!(
        asr_convert::discover_agent(o.agent, &o.input, &o.out)
            .unwrap()
            .len(),
        1
    );
    assert_eq!(convert(&o).unwrap().sessions, 1);
    validate(&o);
}

#[test]
fn kiro_collisions_skip_the_conflicting_session_and_keep_independent_sessions() {
    let (temp, mut options, db) = fixture(Agent::Kiro);
    drop(db);
    let sources = temp.path().join("sources");
    fs::create_dir(&sources).unwrap();
    let first = sources.join("first.db");
    fs::rename(&options.input, &first).unwrap();
    fs::copy(&first, sources.join("second.db")).unwrap();
    let db = Connection::open(&first).unwrap();
    db.execute(
        "INSERT INTO conversations_v2 VALUES('/work/other','independent','{\"history\":[]}',2000)",
        [],
    )
    .unwrap();
    drop(db);
    options.input = sources;
    let summary = convert(&options).unwrap();
    assert_eq!(summary.sessions, 1);
    assert_eq!(
        summary.session_diagnostics["kiro:example"]["colliding_session_identity"],
        1
    );
    validate(&options);
    let output = fs::read_dir(&options.out)
        .unwrap()
        .next()
        .unwrap()
        .unwrap()
        .path();
    let header: Value =
        serde_json::from_str(fs::read_to_string(output).unwrap().lines().next().unwrap()).unwrap();
    assert_eq!(header["sessionId"], "independent");
}

#[test]
fn goose_steer_accepts_any_client_and_does_not_establish_human_authorship() {
    for (metadata, origin, author) in [
        (json!({"steer":true}), Some("queued"), None),
        (json!({}), None, None),
        (
            json!({"steer":true,"turnContext":true}),
            Some("injected"),
            Some("harness"),
        ),
        (
            json!({"steer":true,"usage":{"isCompaction":true}}),
            Some("compaction"),
            Some("harness"),
        ),
    ] {
        let (_temp, o, db) = fixture(Agent::Goose);
        db.execute(
            "UPDATE messages SET metadata_json=?1 WHERE role='user'",
            [metadata.to_string()],
        )
        .unwrap();
        let rows = run(&o);
        let prompt = rows
            .iter()
            .find(|r| r["type"] == "message" && r["role"] == "user")
            .unwrap();
        assert_eq!(prompt["author"].as_str(), author);
        assert_eq!(prompt["origin"].as_str(), origin);
    }
}

#[test]
fn openclaw_database_provenance_overrides_human_sender_metadata() {
    for (kind, author, origin) in [
        ("internal_system", "harness", Some("injected")),
        ("inter_session", "agent", None),
    ] {
        let (_temp, o, db) = fixture(Agent::OpenClaw);
        let event = json!({"type":"message","id":"prompt","message":{"role":"user","content":"Native context.","provenance":{"kind":kind},"__openclaw":{"senderIdentity":{"type":"profile","senderKind":"human"}}}});
        db.execute(
            "UPDATE transcript_events SET event_json=?1 WHERE seq=2",
            [event.to_string()],
        )
        .unwrap();
        let rows = run(&o);
        let message = rows
            .iter()
            .find(|r| r["type"] == "message" && r["id"] == "prompt")
            .unwrap();
        assert_eq!(message["author"], author);
        assert_eq!(message["origin"].as_str(), origin);
        assert!(message.get("person").is_none());
    }
}

#[test]
fn openclaw_results_name_only_emitted_store_decisions() {
    let (_temp, o, db) = fixture(Agent::OpenClaw);
    // Store rows answer five requests. The fixture's `decision` row is gone,
    // so the result naming it keeps no link. `prompt` reuses an event ID.
    db.execute_batch("DROP TABLE operator_approvals; CREATE TABLE operator_approvals(approval_id TEXT PRIMARY KEY,source_session_id TEXT,status TEXT,decision TEXT,resolved_at_ms INTEGER,resolver_kind TEXT,terminal_reason TEXT,source_tool_call_id TEXT); INSERT INTO operator_approvals VALUES('approval-run','example','allowed','allow-once',1500,'device',NULL,'exec-1'),('approval-deny','example','denied','deny',1600,'device',NULL,'exec-2'),('prompt','example','allowed','allow-once',1700,'device',NULL,'exec-3'),('approval-wait','example','allowed','allow-once',1800,'runtime','user','exec-4'),('approval-call','example','allowed','allow-once',1900,'runtime','user','exec-5');").unwrap();
    let call = |id: &str| json!({"type":"toolCall","id":id,"name":"exec","arguments":{"command":"echo approval-test"}});
    let calls: Vec<_> = (1..=5).map(|n| call(&format!("exec-{n}"))).collect();
    let assistant = json!({"type":"message","id":"exec-calls","message":{"role":"assistant","responseId":"response-2","model":"requested-model","content":calls}});
    let result = |call: &str, error: bool, details: Value| json!({"type":"message","id":format!("{call}-result"),"message":{"role":"toolResult","toolCallId":call,"isError":error,"content":[{"type":"text","text":"output"}],"details":details}});
    let events = [
        assistant,
        result(
            "exec-1",
            false,
            json!({"status":"completed","exitCode":0,"aggregated":"approval-test\n","approvalId":"approval-run"}),
        ),
        result(
            "exec-2",
            true,
            json!({"status":"failed","reason":"policy-denied","approvalId":"approval-deny"}),
        ),
        result(
            "exec-3",
            false,
            json!({"status":"completed","exitCode":0,"approvalId":"prompt"}),
        ),
        // OpenClaw 2026.10.10 writes `approvalId` only on a pending receipt,
        // which comes before the decision. Finished exec details omit it.
        result(
            "exec-4",
            false,
            json!({"status":"approval-pending","approvalId":"approval-wait","approvalSlug":"wait","host":"gateway","command":"echo approval-test"}),
        ),
        result(
            "exec-5",
            false,
            json!({"status":"completed","exitCode":0,"exitSignal":null,"exitReason":"exit","durationMs":12,"aggregated":"approval-test","noOutputTimedOut":false,"cwd":"/work/app"}),
        ),
    ];
    for (seq, event) in (6..).zip(events) {
        db.execute(
            "INSERT INTO transcript_events VALUES('example',?1,?2,NULL,NULL)",
            params![seq, event.to_string()],
        )
        .unwrap();
    }
    let r = run(&o);
    let at = |call: &str| {
        r.iter()
            .position(|v| v["type"] == "tool_result" && v["callId"] == call)
            .unwrap()
    };
    for (call, status, decision) in [
        ("exec-1", "completed", "approved"),
        ("exec-2", "denied", "denied"),
        ("exec-3", "completed", "approved"),
    ] {
        let index = at(call);
        let approval = &r[index - 1];
        assert_eq!(r[index]["status"], status);
        assert_eq!(approval["type"], "approval");
        assert_eq!(approval["decision"], decision);
        assert_eq!(approval["callId"], call);
        assert_eq!(r[index]["approvalId"], approval["id"], "{call}");
    }
    // A shared ID is remapped, and the link follows the approval's output ID.
    assert_ne!(r[at("exec-3")]["approvalId"], "prompt");
    // A pending receipt or a row for the same call does not state which
    // decision a result followed.
    assert_eq!(r[at("exec-4")]["status"], "unknown");
    for call in ["exec-4", "exec-5"] {
        assert!(r[at(call)].get("approvalId").is_none(), "{call}");
    }
    let missing = r.iter().find(|v| v["id"] == "approval-result").unwrap();
    assert!(missing.get("approvalId").is_none());
    assert_eq!(r.iter().filter(|v| v["type"] == "approval").count(), 3);
    assert!(r.iter().all(|v| !matches!(
        v["native"]["approval_id"].as_str(),
        Some("decision" | "approval-wait" | "approval-call")
    )));
}
