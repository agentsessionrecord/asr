use asr_convert::{convert, Agent, Options};
use rusqlite::Connection;
use serde_json::{json, Value};
use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
};
const AGENTS: [Agent; 9] = [
    Agent::Auggie,
    Agent::Cline,
    Agent::CodeBuddy,
    Agent::Continue,
    Agent::Hermes,
    Agent::NanoClaw,
    Agent::OpenHands,
    Agent::RooCode,
    Agent::RovoDev,
];
fn fixtures() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/documents")
}
fn copy_tree(source: &Path, out: &Path) {
    fs::create_dir_all(out).unwrap();
    for entry in fs::read_dir(source).unwrap() {
        let entry = entry.unwrap();
        let target = out.join(entry.file_name());
        if entry.path().is_dir() {
            copy_tree(&entry.path(), &target);
        } else {
            fs::copy(entry.path(), target).unwrap();
        }
    }
}
fn fixture(agent: Agent, root: &Path) -> PathBuf {
    let input = root.join("native");
    copy_tree(&fixtures().join(agent.name()), &input);
    let sql = |source: &str, out: &Path| {
        fs::create_dir_all(out.parent().unwrap()).unwrap();
        Connection::open(out)
            .unwrap()
            .execute_batch(&fs::read_to_string(input.join(source)).unwrap())
            .unwrap();
    };
    if agent == Agent::Hermes {
        sql("state.sql", &input.join("state.db"));
    }
    if agent == Agent::NanoClaw {
        sql("inventory.sql", &input.join("data/v2.db"));
        sql(
            "inbound.sql",
            &input.join("data/v2-sessions/group-sample/nano-sample/inbound.db"),
        );
        sql(
            "outbound.sql",
            &input.join("data/v2-sessions/group-sample/nano-sample/outbound.db"),
        );
    }
    input
}
fn data(out: &Path) -> Vec<Value> {
    let path = fs::read_dir(out)
        .unwrap()
        .map(|e| e.unwrap().path())
        .find(|p| p.extension().is_some_and(|x| x == "jsonl"))
        .unwrap();
    fs::read_to_string(path)
        .unwrap()
        .lines()
        .map(|s| serde_json::from_str(s).unwrap())
        .collect()
}
fn bytes(out: &Path) -> Vec<u8> {
    fs::read(
        fs::read_dir(out)
            .unwrap()
            .map(|e| e.unwrap().path())
            .find(|p| p.extension().is_some_and(|x| x == "jsonl"))
            .unwrap(),
    )
    .unwrap()
}
fn validate(out: &Path) {
    let validator =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tools/validator/bin/asr-validate.js");
    let result = Command::new("node")
        .arg(validator)
        .args(["--summary", "--json"])
        .arg(out)
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
}
fn run(agent: Agent) -> (tempfile::TempDir, Vec<Value>) {
    let temp = tempfile::tempdir().unwrap();
    let input = fixture(agent, temp.path());
    let out = temp.path().join("out");
    assert_eq!(
        convert(&Options::new(agent, input, out.clone()))
            .unwrap()
            .sessions,
        1
    );
    validate(&out);
    let data = data(&out);
    (temp, data)
}
#[test]
fn document_goldens_match_sources_and_are_location_independent() {
    for agent in AGENTS {
        let temp = tempfile::tempdir().unwrap();
        let input = fixture(agent, temp.path());
        let out = temp.path().join("out");
        let summary = convert(&Options::new(agent, input.clone(), out.clone())).unwrap();
        assert_eq!(summary.sessions, 1, "{}", agent.name());
        validate(&out);
        let actual = bytes(&out);
        let golden = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join(format!("tests/golden/{}.jsonl", agent.name()));
        if std::env::var_os("ASR_UPDATE_DOCUMENT_GOLDENS").is_some() {
            fs::write(&golden, &actual).unwrap();
        }
        assert_eq!(actual, fs::read(golden).unwrap(), "{}", agent.name());
        let moved = temp.path().join("moved");
        copy_tree(&input, &moved);
        convert(&Options::new(agent, moved, out.clone())).unwrap();
        assert_eq!(actual, bytes(&out), "{} relocated", agent.name());
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                fs::metadata(&out).unwrap().permissions().mode() & 0o777,
                0o700
            );
            for entry in fs::read_dir(&out).unwrap() {
                assert_eq!(
                    entry.unwrap().metadata().unwrap().permissions().mode() & 0o777,
                    0o600
                );
            }
        }
    }
}
#[test]
fn roles_models_times_and_outcomes_require_evidence() {
    for agent in AGENTS {
        let (_, records) = run(agent);
        assert!(records.iter().all(|r| r["author"] != "human"));
        assert!(records.iter().all(|r| r["type"] != "inference"));
        assert!(records.iter().all(|r| r["type"] != "approval"));
        assert!(records.iter().all(|r| r["type"] != "file_change"));
        if !matches!(agent, Agent::Hermes) {
            assert!(records.iter().all(|r| r.get("endedAt").is_none()));
        }
        if matches!(agent, Agent::CodeBuddy | Agent::RovoDev) {
            assert!(records
                .iter()
                .filter(|r| r["type"] == "tool_result")
                .all(|r| r["status"] == "unknown"));
        }
    }
}
#[test]
fn exact_text_parts_and_wide_arguments_survive() {
    let (_, a) = run(Agent::Auggie);
    let replies: Vec<_> = a
        .iter()
        .filter(|v| v["type"] == "message" && v["role"] == "assistant")
        .collect();
    assert_eq!(
        replies[0]["content"],
        json!([{"type":"text","text":"First\n"},{"type":"text","text":"Second"}])
    );
    assert!(replies[0].get("ts").is_none());
    assert_eq!(
        a.iter().find(|v| v["type"] == "message").unwrap()["content"][0]["text"],
        "  Inspect the file.\n"
    );
    let (_, cline) = run(Agent::Cline);
    let call = cline.iter().find(|v| v["type"] == "tool_call").unwrap();
    assert_eq!(call["input"]["exact"], "9007199254740993");
    assert_eq!(
        cline.iter().find(|v| v["type"] == "tool_result").unwrap()["content"][0]["text"],
        "  ready\n"
    );
    let (_, buddy) = run(Agent::CodeBuddy);
    assert_eq!(
        buddy.iter().find(|v| v["type"] == "message").unwrap()["content"][0]["text"],
        "<user_query>  Keep these bytes.\n</user_query>"
    );
}
#[test]
fn native_order_totals_parent_links_and_compaction() {
    let (_, h) = run(Agent::Hermes);
    assert_eq!(h[0]["parent"]["session"], "hermes:parent%3Athree");
    let messages: Vec<_> = h.iter().filter(|v| v["type"] == "message").collect();
    assert!(messages[0]["ts"].as_str().unwrap() > messages[1]["ts"].as_str().unwrap());
    assert_eq!(
        h.iter().find(|v| v["type"] == "session_info").unwrap()["usage"]["inputTokens"],
        0
    );
    assert!(
        h.iter().rposition(|v| v["type"] == "tool_result").unwrap()
            < h.iter().position(|v| v["type"] == "session_info").unwrap()
    );
    assert_eq!(
        h.iter().find(|v| v["type"] == "session_info").unwrap()["cost"]["amount"],
        0.0
    );
    let (_, o) = run(Agent::OpenHands);
    let types: Vec<_> = o
        .iter()
        .filter_map(|r| {
            let t = r["type"].as_str()?;
            matches!(t, "message" | "tool_call" | "tool_result").then_some(t)
        })
        .collect();
    assert_eq!(types, ["message", "tool_call", "tool_result"]);
    let (_, cont) = run(Agent::Continue);
    let index = cont
        .iter()
        .position(|r| r["origin"] == "compaction")
        .unwrap();
    assert_eq!(cont[index + 1]["type"], "gap");
    let (_, nano) = run(Agent::NanoClaw);
    let m = nano.iter().find(|r| r["type"] == "message").unwrap();
    assert_eq!(m["origin"], "scheduled");
    assert!(m.get("author").is_none());
}
fn single(agent: Agent, value: &Value) -> (tempfile::TempDir, Vec<Value>) {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("session.json");
    fs::write(&input, format!("{value}\n")).unwrap();
    let out = temp.path().join("out");
    convert(&Options::new(agent, input, out.clone())).unwrap();
    validate(&out);
    let records = data(&out);
    (temp, records)
}
#[test]
fn secret_answers_redact_all_representations_and_unknown_events_remain() {
    let secret = "synthetic private answer value";
    let input = json!({"sessionId":"private-sample","messages":[{"role":"assistant","content":[{"type":"tool_use","id":"q","name":"question","input":{"questions":[{"id":"q","secret":true,"question":"Synthetic secret question"}]}}]},{"role":"user","answers":{"q":secret},"content":secret},{"role":"assistant","content":[{"type":"future_part","text":"retained unknown","password":secret,"signature":"opaque-sample"}]}]});
    let (_, records) = single(Agent::Cline, &input);
    let raw = serde_json::to_string(&records).unwrap();
    assert!(!raw.contains(secret));
    assert!(!raw.contains("opaque-sample"));
    assert!(raw.contains("retained unknown"));
    assert!(records[0]["missing"]
        .as_array()
        .unwrap()
        .iter()
        .any(|v| v == "redacted_content"));
    assert!(records.iter().any(|v| v["truncated"] == true));
}
#[test]
fn malformed_complete_lines_become_gaps_and_incomplete_tails_wait() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("session.jsonl");
    fs::write(&input,"{\"sessionId\":\"recovery\",\"role\":\"user\",\"content\":\"before\"}\n{\"x\":1,\"x\":2}\n{\"role\":\"assistant\",\"content\":\"after\"}\n{\"role\":\"user\"").unwrap();
    let out = temp.path().join("out");
    let summary = convert(&Options::new(Agent::CodeBuddy, input, out.clone())).unwrap();
    validate(&out);
    let records = data(&out);
    assert_eq!(summary.diagnostics["unparseable_source_line"], 1);
    assert_eq!(summary.diagnostics["incomplete_source_tail"], 1);
    assert!(records.iter().any(|v| v["type"] == "gap"));
    assert!(records.iter().any(|v| v["content"][0]["text"] == "after"));
}
#[test]
fn repeated_results_fold_at_completion_and_conflicting_aliases_do_not_pair() {
    let (_, records) = single(
        Agent::Cline,
        &json!({"sessionId":"fold-sample","messages":[{"role":"assistant","content":[{"type":"tool_use","id":"run","name":"shell","input":null}]},{"role":"user","content":[{"type":"tool_result","tool_use_id":"run","status":"failed","content":"first"}]},{"id":"notice","role":"system","content":"intervening"},{"timestamp":"2026-10-31T12:00:03Z","role":"user","content":[{"type":"tool_result","tool_use_id":"run","content":"last"}]},{"role":"tool","tool_call_id":"one","tool_use_id":"two","content":"ambiguous"}]}),
    );
    let result = records
        .iter()
        .find(|r| r["callId"] == "run" && r["type"] == "tool_result")
        .unwrap();
    assert_eq!(result["status"], "failed");
    assert_eq!(result["content"][0]["text"], "last");
    let notice = records.iter().position(|r| r["id"] == "notice").unwrap();
    let completed = records
        .iter()
        .position(|r| r["callId"] == "run" && r["type"] == "tool_result")
        .unwrap();
    assert!(notice < completed);
    assert!(records.iter().any(|r| r["type"] == "tool_result"
        && r["content"][0]["text"] == "ambiguous"
        && r.get("callId").is_none()));
}
#[test]
fn oversized_sqlite_rows_emit_gaps_without_mutating_the_source() {
    let temp = tempfile::tempdir().unwrap();
    let input = fixture(Agent::Hermes, temp.path());
    let path = input.join("state.db");
    let db = Connection::open(&path).unwrap();
    db.execute(
        "UPDATE messages SET content=?1 WHERE id=1",
        ["x".repeat(8192)],
    )
    .unwrap();
    drop(db);
    let before = fs::read(&path).unwrap();
    let out = temp.path().join("out");
    let mut options = Options::new(Agent::Hermes, input, out.clone());
    options.max_record_bytes = 4096;
    let summary = convert(&options).unwrap();
    validate(&out);
    assert_eq!(summary.diagnostics["oversized_source_row"], 1);
    assert!(data(&out).iter().any(|r| r["type"] == "gap"));
    assert_eq!(before, fs::read(&path).unwrap());
}
#[test]
fn duplicate_document_keys_and_conflicting_session_aliases_are_rejected() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("session.json");
    let out = temp.path().join("out");
    fs::write(
        &input,
        "{\"sessionId\":\"one\",\"sessionId\":\"two\",\"history\":[]}",
    )
    .unwrap();
    let summary = convert(&Options::new(Agent::Continue, input.clone(), out.clone())).unwrap();
    assert_eq!(summary.sessions, 0);
    assert_eq!(summary.diagnostics["unparseable_source_document"], 1);
    fs::write(
        &input,
        "{\"sessionId\":\"one\",\"session_id\":\"two\",\"chatHistory\":[]}",
    )
    .unwrap();
    let summary = convert(&Options::new(Agent::Auggie, input, out)).unwrap();
    assert_eq!(summary.sessions, 0);
    assert_eq!(summary.diagnostics["unidentified_source"], 1);
}

#[test]
fn extension_indexes_follow_only_native_local_message_ids() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("history/project/session");
    fs::create_dir_all(input.join("messages")).unwrap();
    fs::write(
        input.join("index.json"),
        json!({"messages":[{"id":"prompt","role":"user"},{"id":"../outside","role":"user"}]})
            .to_string(),
    )
    .unwrap();
    fs::write(
        input.join("messages/prompt.json"),
        json!({"message":"{\"content\":\"  exact extension text\\n\"}"}).to_string(),
    )
    .unwrap();
    let out = temp.path().join("out");
    let summary = convert(&Options::new(
        Agent::CodeBuddy,
        temp.path().join("history"),
        out.clone(),
    ))
    .unwrap();
    assert_eq!(summary.sessions, 1);
    assert_eq!(summary.diagnostics["invalid_message_reference"], 1);
    validate(&out);
    let records = data(&out);
    assert_eq!(records[0]["sessionId"], "session");
    assert_eq!(
        records.iter().find(|r| r["type"] == "message").unwrap()["content"][0]["text"],
        "  exact extension text\n"
    );
}
#[test]
fn sdk_event_directory_and_naive_time_keep_native_identity_without_guessing_time() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("v1_conversations/sdk-native");
    fs::create_dir_all(&input).unwrap();
    fs::write(input.join("event-00001-source.json"),json!({"id":"event-native","kind":"MessageEvent","timestamp":"2026-10-31T12:00:00","llm_message":{"role":"assistant","content":"native reply"}}).to_string()).unwrap();
    let out = temp.path().join("out");
    convert(&Options::new(
        Agent::OpenHands,
        temp.path().join("v1_conversations"),
        out.clone(),
    ))
    .unwrap();
    validate(&out);
    let records = data(&out);
    assert_eq!(records[0]["sessionId"], "sdk-native");
    let m = records.iter().find(|r| r["type"] == "message").unwrap();
    assert_eq!(m["id"], "event-native");
    assert!(m.get("ts").is_none());
}
#[test]
fn redaction_marks_the_actual_shortened_message_and_null_arguments_survive() {
    let secret = "synthetic credential value";
    let (_, records) = single(
        Agent::Cline,
        &json!({"sessionId":"redaction","messages":[{"role":"user","content":secret},{"role":"assistant","content":[{"type":"tool_use","id":"call","name":"synthetic","input":null}],"password":secret}]}),
    );
    let m = records
        .iter()
        .find(|r| r["type"] == "message" && r["role"] == "user")
        .unwrap();
    assert_eq!(m["truncated"], true);
    let call = records.iter().find(|r| r["type"] == "tool_call").unwrap();
    assert!(call.get("input").unwrap().is_null());
}

#[test]
fn corrupt_event_documents_keep_a_gap_at_the_native_position() {
    let temp = tempfile::tempdir().unwrap();
    let input = fixture(Agent::OpenHands, temp.path());
    fs::write(
        input.join("conversations/openhands-sample/events/2.json"),
        "{broken complete document}",
    )
    .unwrap();
    let out = temp.path().join("out");
    let summary = convert(&Options::new(Agent::OpenHands, input, out.clone())).unwrap();
    assert_eq!(summary.diagnostics["unparseable_source_document"], 1);
    validate(&out);
    let records = data(&out);
    assert_eq!(records[0]["sessionId"], "openhands-sample");
    let gap = records.iter().position(|r| r["type"] == "gap").unwrap();
    assert!(records[..gap].iter().any(|r| r["type"] == "message"));
    assert!(records[gap..].iter().any(|r| r["type"] == "tool_result"));
}
#[test]
fn unsupported_message_content_is_preserved_as_vendor_evidence() {
    let (_, records) = single(
        Agent::Cline,
        &json!({"sessionId":"future-sample","messages":[{"role":"assistant","content":[{"future":true,"value":"retained future content"}]}]}),
    );
    assert!(serde_json::to_string(&records)
        .unwrap()
        .contains("retained future content"));
}

#[test]
fn fractional_epoch_timestamps_preserve_nanoseconds_without_rounding() {
    let (_, records) = single(
        Agent::Cline,
        &json!({"sessionId":"fractional-times","messages":[
            {"id":"seconds","role":"user","content":"seconds","timestamp":"1793448000.123456789"},
            {"id":"millis","role":"user","content":"millis","timestamp":"1793448000123.456789"},
            {"id":"negative","role":"user","content":"negative","timestamp":"-0.000000001"},
            {"id":"too_precise","role":"user","content":"too precise","timestamp":"1793448000123.4567891"}
        ]}),
    );
    for id in ["seconds", "millis"] {
        assert_eq!(
            records.iter().find(|r| r["id"] == id).unwrap()["ts"],
            "2026-10-31T12:00:00.123456789Z"
        );
    }
    assert_eq!(
        records.iter().find(|r| r["id"] == "negative").unwrap()["ts"],
        "1969-12-31T23:59:59.999999999Z"
    );
    assert!(records
        .iter()
        .find(|r| r["id"] == "too_precise")
        .unwrap()
        .get("ts")
        .is_none());
}

#[test]
fn hermes_input_includes_cache_once_and_unknown_components_remain_unknown() {
    let temp = tempfile::tempdir().unwrap();
    let input = fixture(Agent::Hermes, temp.path());
    let db = Connection::open(input.join("state.db")).unwrap();
    db.execute_batch(
        "ALTER TABLE sessions ADD COLUMN cache_read_tokens INTEGER;
         ALTER TABLE sessions ADD COLUMN cache_write_tokens INTEGER;
         ALTER TABLE sessions ADD COLUMN reasoning_tokens INTEGER;
         UPDATE sessions SET input_tokens=10, cache_read_tokens=20,
                             cache_write_tokens=3, reasoning_tokens=2;",
    )
    .unwrap();
    let out = temp.path().join("out");
    for (read, total) in [(Some(20), Some(33)), (None, None), (Some(i64::MAX), None)] {
        db.execute("UPDATE sessions SET cache_read_tokens=?1", [read])
            .unwrap();
        convert(&Options::new(Agent::Hermes, input.clone(), out.clone())).unwrap();
        validate(&out);
        let records = data(&out);
        let info = records
            .iter()
            .find(|r| r["type"] == "session_info")
            .unwrap();
        assert_eq!(info["usage"]["inputTokens"].as_u64(), total);
        assert_eq!(info["usage"]["outputTokens"], 7);
        assert_eq!(info["usage"]["reasoningTokens"], 2);
        assert_eq!(info["usage"]["cacheWriteTokens"], 3);
        if read == Some(20) {
            assert_eq!(info["usage"]["cacheReadTokens"], 20);
        }
    }
}
