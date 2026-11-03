use asr_convert::{convert, Agent, Options, Summary};
use serde_json::{json, Value};
use std::{
    fs,
    io::Write,
    path::{Path, PathBuf},
    process::Command,
};

const AGENTS: [Agent; 5] = [
    Agent::Cursor,
    Agent::GeminiCli,
    Agent::MistralVibe,
    Agent::Mux,
    Agent::Fx,
];
fn fixtures() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/w1-conv-a")
}
fn write(path: &Path, rows: &[Value]) {
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(
        path,
        rows.iter().map(|v| format!("{v}\n")).collect::<String>(),
    )
    .unwrap();
}
fn read(out: &Path) -> Vec<Value> {
    let mut files = fs::read_dir(out)
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| p.extension().is_some_and(|v| v == "jsonl"))
        .collect::<Vec<_>>();
    files.sort();
    assert_eq!(files.len(), 1);
    fs::read_to_string(&files[0])
        .unwrap()
        .lines()
        .map(|s| serde_json::from_str(s).unwrap())
        .collect()
}
fn validate(out: &Path) {
    let r = Command::new("node")
        .arg(
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tools/validator/bin/asr-validate.js"),
        )
        .args(["--json", "--summary"])
        .arg(out)
        .output()
        .unwrap();
    assert!(r.status.success(), "{}", String::from_utf8_lossy(&r.stdout));
}
fn run(agent: Agent, input: &Path, out: &Path) -> (Summary, Vec<Value>) {
    let summary = convert(&Options::new(agent, input.to_owned(), out.to_owned())).unwrap();
    validate(out);
    (summary, read(out))
}
fn one(agent: Agent, rows: &[Value]) -> (tempfile::TempDir, Vec<Value>) {
    let t = tempfile::tempdir().unwrap();
    let p = t.path().join("native.jsonl");
    write(&p, rows);
    let (_, r) = run(agent, &p, &t.path().join("out"));
    (t, r)
}
#[test]
fn five_synthetic_goldens_are_exact_and_deterministic() {
    for agent in AGENTS {
        let t = tempfile::tempdir().unwrap();
        let out = t.path().join("out");
        let input = fixtures().join(agent.name());
        let (summary, r) = run(agent, &input, &out);
        assert_eq!(summary.sessions, 1, "{}", agent.name());
        let actual = r.iter().map(|v| format!("{v}\n")).collect::<String>();
        let golden = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join(format!("tests/golden-w1-conv-a/{}.jsonl", agent.name()));
        if std::env::var_os("ASR_UPDATE_W1A_GOLDENS").is_some() {
            fs::write(golden, &actual).unwrap();
        }
        let expected = fs::read_to_string(
            Path::new(env!("CARGO_MANIFEST_DIR"))
                .join(format!("tests/golden-w1-conv-a/{}.jsonl", agent.name())),
        )
        .unwrap();
        assert_eq!(actual, expected, "{}", agent.name());
        let (_, again) = run(agent, &input, &out);
        assert_eq!(r, again);
        assert_eq!(r[0]["agent"]["name"], agent.name());
        assert!(r.iter().all(|r| r["type"] != "approval"));
        if agent != Agent::GeminiCli {
            assert!(r.iter().all(|r| r["type"] != "inference"));
        }
    }
}
#[test]
fn gemini_usage_file_states_masking_and_requested_model() {
    let t = tempfile::tempdir().unwrap();
    let (_, r) = run(
        Agent::GeminiCli,
        &fixtures().join("gemini-cli"),
        &t.path().join("out"),
    );
    let inf = r.iter().find(|r| r["type"] == "inference").unwrap();
    assert_eq!(inf["usage"], json!({"inputTokens":10,"outputTokens":5}));
    assert_eq!(inf["model"], json!({"requested":"example-model"}));
    let change = r.iter().find(|r| r["type"] == "file_change").unwrap();
    assert_eq!(change["status"], "applied");
    assert_eq!(change["before"]["text"], "limit = int(value)\n");
    let (_, r) = one(
        Agent::GeminiCli,
        &[
            json!({"sessionId":"mask"}),
            json!({"id":"m","type":"gemini","tokens":{"input":0,"output":2,"thoughts":3,"cached":0},"content":[{"functionResponse":{"id":"unavailable","response":{"output":"<tool_output_masked>private</tool_output_masked>"}}},{"inlineData":{"mimeType":"image/png","data":"AAAA"}}]}),
        ],
    );
    let inf = r.iter().find(|r| r["type"] == "inference").unwrap();
    assert_eq!(inf["usage"]["outputTokens"], 5);
    assert_eq!(inf["usage"]["cacheReadTokens"], 0);
    assert!(inf.get("model").is_none());
    let result = r.iter().find(|r| r["type"] == "tool_result").unwrap();
    assert_eq!(result["truncated"], true);
    assert!(r
        .iter()
        .any(|r| r.pointer("/content/0/type") == Some(&json!("image"))));
    let (_, r) = one(
        Agent::GeminiCli,
        &[
            json!({"sessionId":"unknown-count"}),
            json!({"id":"reply","type":"gemini","tokens":{"output":2,"thoughts":9007199254740993u64},"content":[],"toolCalls":[{"id":"c","name":"read_file","status":"success","result":[{"functionResponse":{"id":"c","response":{"output":"first"}}}]}]}),
            json!({"id":"result-copy","type":"user","content":[{"functionResponse":{"id":"c","response":{"output":"final"}}}]}),
        ],
    );
    let inf = r.iter().find(|r| r["type"] == "inference").unwrap();
    assert!(inf["usage"].get("outputTokens").is_none());
    let result = r.iter().find(|r| r["type"] == "tool_result").unwrap();
    assert_eq!(result["status"], "completed");
    assert_eq!(result["content"][0]["text"], "final");
    assert_eq!(r.iter().filter(|r| r["type"] == "tool_result").count(), 1);
}
#[test]
fn gemini_folds_at_last_observation_and_retains_rewound_work() {
    let (_, r) = one(
        Agent::GeminiCli,
        &[
            json!({"sessionId":"fold"}),
            json!({"id":"reply","type":"gemini","timestamp":"2026-10-31T12:00:00Z","content":"a","tokens":{"input":0,"output":0}}),
            json!({"id":"between","type":"user","content":"notice"}),
            json!({"id":"reply","type":"gemini","timestamp":"2026-10-31T12:00:02Z","content":"ab","tokens":{"input":0,"output":2}}),
            json!({"$rewindTo":"between"}),
            json!({"id":"branch","type":"gemini","content":"other branch"}),
        ],
    );
    let reply = r.iter().position(|v| v["id"] == "reply").unwrap();
    let between = r.iter().position(|v| v["id"] == "between").unwrap();
    assert!(reply > between);
    assert_eq!(r[reply]["content"][0]["text"], "ab");
    assert_eq!(r[reply]["ts"], "2026-10-31T12:00:02Z");
    assert_eq!(r.iter().filter(|r| r["type"] == "inference").count(), 1);
    assert!(r.iter().any(|r| r["id"] == "branch"));
}
#[test]
fn gemini_legacy_precedence_child_identity_and_corrupt_recovery() {
    let t = tempfile::tempdir().unwrap();
    let root = t.path().join("chats/parent");
    fs::create_dir_all(&root).unwrap();
    let p = root.join("child.jsonl");
    write(
        &p,
        &[
            json!({"sessionId":"native:child","kind":"subagent"}),
            json!({"type":"user","id":"u","content":"kept"}),
        ],
    );
    fs::write(root.join("child.json"), "invalid obsolete document").unwrap();
    let mut f = fs::OpenOptions::new().append(true).open(&p).unwrap();
    writeln!(f, "{{bad}}").unwrap();
    write!(f, "{{\"tail\":").unwrap();
    let (s, r) = run(Agent::GeminiCli, &root, &t.path().join("out"));
    assert_eq!(s.files, 1);
    assert_eq!(s.diagnostics["unparseable_source_line"], 1);
    assert_eq!(s.diagnostics["incomplete_source_tail"], 1);
    assert_eq!(r[0]["sessionId"], "native:child");
    assert_eq!(r[0]["parent"]["session"], "gemini-cli:parent");
    assert!(r.iter().any(|r| r["type"] == "gap"));
}
#[test]
fn cursor_storage_identity_and_unsupported_roles_stay_conservative() {
    let t = tempfile::tempdir().unwrap();
    let p = t
        .path()
        .join("projects/test/agent-transcripts/native/native.jsonl");
    write(
        &p,
        &[
            json!({"role":"user","message":{"content":[{"type":"tool_use","id":"not-model","name":"execute","input":{}},{"type":"text","text":"Question"}]}}),
            json!({"role":"assistant","message":{"role":"user","content":[{"type":"tool_use","id":"conflict","name":"execute"}]}}),
            json!({"role":"assistant","message":{"content":[{"type":"tool_use","id":"actual","name":"read","input":{}}]}}),
            json!({"role":"user","message":{"content":[{"type":"tool_result","tool_use_id":"actual","is_error":false,"content":"done"}]}}),
        ],
    );
    let (_, r) = run(Agent::Cursor, &p, &t.path().join("out"));
    assert_eq!(r[0]["sessionId"], "native");
    assert_eq!(r.iter().filter(|r| r["type"] == "tool_call").count(), 1);
    assert_eq!(
        r.iter().find(|r| r["type"] == "tool_call").unwrap()["callId"],
        "actual"
    );
    assert!(r.iter().all(|r| r.get("author") != Some(&json!("human"))));
    let renamed = t.path().join("unbound.jsonl");
    fs::copy(&p, &renamed).unwrap();
    assert_eq!(
        convert(&Options::new(
            Agent::Cursor,
            renamed,
            t.path().join("unbound")
        ))
        .unwrap()
        .sessions,
        0
    );
}
#[test]
fn mux_partial_replaces_only_matching_sequence_and_does_not_invent_model_output() {
    let t = tempfile::tempdir().unwrap();
    let root = t.path().join("sessions/native");
    let p = root.join("chat.jsonl");
    write(
        &p,
        &[
            json!({"id":"old","workspaceId":"native","role":"assistant","parts":[{"type":"text","text":"old"}],"metadata":{"historySequence":1}}),
        ],
    );
    fs::write(root.join("partial.json"),json!({"id":"new","role":"assistant","parts":[{"type":"text","text":"new"},{"type":"dynamic-tool","toolCallId":"c","toolName":"shell","input":{},"state":"output-available","output":"display-only"}],"metadata":{"historySequence":1,"partial":true,"usage":{"inputTokens":1}}}).to_string()).unwrap();
    let (_, r) = run(Agent::Mux, &root, &t.path().join("out"));
    assert!(!r.iter().any(|r| r["id"] == "old"));
    assert!(r.iter().any(|r| r["id"] == "new"));
    let result = r.iter().find(|r| r["type"] == "tool_result").unwrap();
    assert_eq!(result["status"], "unknown");
    assert!(result.get("content").is_none());
    assert!(r.iter().all(|r| r["type"] != "inference"));
}
#[test]
fn mux_checks_identity_across_archive_active_and_partial() {
    for companion in ["chat-archive.jsonl", "partial.json", "metadata.json"] {
        let t = tempfile::tempdir().unwrap();
        let root = t.path().join("native");
        write(
            &root.join("chat.jsonl"),
            &[
                json!({"workspaceId":"native","id":"active","role":"user","parts":[{"type":"text","text":"Active prompt"}]}),
            ],
        );
        write(
            &root.join(companion),
            &[json!({"workspaceId":"different","id":"companion","role":"user","parts":[]})],
        );
        let summary = convert(&Options::new(Agent::Mux, root, t.path().join("out"))).unwrap();
        assert_eq!(summary.sessions, 0, "{companion}");
        assert_eq!(summary.diagnostics["ambiguous_source_identity"], 1);
    }
    let t = tempfile::tempdir().unwrap();
    let p = t.path().join("partial.json");
    fs::write(&p, json!({"workspaceId":"partial-only","id":"p","role":"user","parts":[{"type":"text","text":"Partial prompt"}]}).to_string()).unwrap();
    let (_, r) = run(Agent::Mux, &p, &t.path().join("out"));
    assert_eq!(r[0]["sessionId"], "partial-only");
    assert!(r.iter().any(|r| r["id"] == "p"));
}
#[test]
fn vibe_manual_shell_and_compaction_keep_native_outcomes_and_ownership() {
    let t = tempfile::tempdir().unwrap();
    let p = t.path().join("messages.jsonl");
    fs::write(t.path().join("meta.json"),json!({"session_id":"vibe","parent_session_id":"related","stats":{"session_prompt_tokens":0,"session_completion_tokens":2}}).to_string()).unwrap();
    write(
        &p,
        &[
            json!({"role":"user","content":"summary","context_boundary":"compaction"}),
            json!({"role":"assistant","content":"done","manual_shell":{"operation_id":"s","command":"echo example","exit_code":0,"stdout":"example\n","interrupted":false}}),
        ],
    );
    let (_, r) = run(Agent::MistralVibe, &p, &t.path().join("out"));
    assert!(r[0].get("parent").is_none());
    assert!(r.iter().any(|r| r["type"] == "gap"));
    let call = r.iter().find(|r| r["type"] == "tool_call").unwrap();
    assert_eq!(call["requestedBy"], "user");
    let result = r.iter().find(|r| r["type"] == "tool_result").unwrap();
    assert_eq!(result["status"], "unknown");
    assert_eq!(result["exec"]["exitCode"], 0);
}
fn fx_copy(root: &Path) -> PathBuf {
    let source = fixtures().join("fx/sessions/synthetic-fx");
    fs::create_dir_all(root).unwrap();
    for e in fs::read_dir(source).unwrap() {
        let e = e.unwrap();
        fs::copy(e.path(), root.join(e.file_name())).unwrap();
    }
    root.join("events.jsonl")
}
#[test]
fn fx_ignores_uncommitted_tail_and_refuses_pending_or_invalid_watermark() {
    let t = tempfile::tempdir().unwrap();
    let p = fx_copy(&t.path().join("native"));
    let out = t.path().join("out");
    let (_, before) = run(Agent::Fx, &p, &out);
    writeln!(
        fs::OpenOptions::new().append(true).open(&p).unwrap(),
        "private uncommitted bytes"
    )
    .unwrap();
    let (_, after) = run(Agent::Fx, &p, &out);
    assert_eq!(before, after);
    fs::write(p.with_file_name("commit.pending.json"), "{}").unwrap();
    assert!(convert(&Options::new(Agent::Fx, p.clone(), out.clone())).is_err());
    assert_eq!(read(&out), before);
    fs::remove_file(p.with_file_name("commit.pending.json")).unwrap();
    let wm = p.with_file_name(format!("commit.{}.json", "1".repeat(32)));
    let mut v: Value = serde_json::from_str(&fs::read_to_string(&wm).unwrap()).unwrap();
    v["through_seq"] = json!(100);
    fs::write(wm, v.to_string()).unwrap();
    assert!(convert(&Options::new(Agent::Fx, p, out)).is_err());
}
#[test]
fn secret_answers_opaque_state_and_large_native_numbers_do_not_leak_or_round() {
    let secret = "SYNTHETIC_PRIVATE_ANSWER_1472";
    let (_, r) = one(
        Agent::GeminiCli,
        &[
            json!({"sessionId":"private"}),
            json!({"id":"ask","type":"gemini","content":[],"toolCalls":[{"id":"q","name":"request_user_input","args":{"questions":[{"id":"token","secret":true,"question":"Synthetic credential"}]},"result":[{"functionResponse":{"id":"q","response":{"answers":{"token":secret}}}}]}]}),
            json!({"id":"echo","type":"gemini","content":[{"text":secret,"thoughtSignature":"UNSAFE_PROVIDER_STATE"}],"tokens":{"input":9007199254740993u64,"output":0},"toolCalls":[{"id":"exact","name":"tool","args":{"native":9007199254740993u64}}]}),
        ],
    );
    let text = serde_json::to_string(&r).unwrap();
    assert!(!text.contains(secret));
    assert!(!text.contains("UNSAFE_PROVIDER_STATE"));
    let call = r
        .iter()
        .find(|r| r["type"] == "tool_call" && r["callId"] == "exact")
        .unwrap();
    assert_eq!(call["input"]["native"], "9007199254740993");
    assert!(r[0]["missing"]
        .as_array()
        .unwrap()
        .contains(&json!("redacted_content")));
}

#[test]
fn fx_replacements_verify_chunks_keep_prior_work_and_exclude_encoded_secrets() {
    use base64::{engine::general_purpose::STANDARD, Engine};
    use sha2::{Digest, Sha256};
    let t = tempfile::tempdir().unwrap();
    let p = fx_copy(&t.path().join("native"));
    let state = json!({"id":"synthetic-fx","history":[{"kind":"compacted_summary","summary":"Available summary"},{"kind":"assistant","user":{"text":"Synthetic question"},"assistant":"Done","execution":{"tool_steps":[{"tool_calls":[{"id":"secret","name":"request_user_input","arguments_json":"{\"questions\":[{\"id\":\"answer\",\"secret\":true}]}"}],"tool_results":[{"tool_call_id":"secret","status":"success","output":"{\"answers\":{\"answer\":\"SYNTHETIC_REPLACEMENT_SECRET_914\"}}"}]}]}}]});
    let bytes = serde_json::to_vec(&state).unwrap();
    let hash = format!("{:x}", Sha256::digest(&bytes));
    let encoded = STANDARD.encode(&bytes);
    let replacement = "b".repeat(32);
    let generation = "1".repeat(32);
    let frame = |seq: u64, kind: &str, payload: Value| json!({"schema_version":1,"log_generation":generation,"seq":seq,"event_id":format!("{seq:032x}"),"timestamp_ms":1700000000000u64+seq,"kind":kind,"payload":payload});
    let start = json!({"replacement_id":replacement,"encoded_bytes":bytes.len(),"sha256":hash,"chunk_count":1});
    let mut log = fs::OpenOptions::new().append(true).open(&p).unwrap();
    for row in [
        frame(3, "state_replacement_started", start.clone()),
        frame(
            4,
            "state_replacement_chunk",
            json!({"replacement_id":replacement,"chunk_index":0,"raw_bytes":bytes.len(),"chunk_sha256":hash,"base64":encoded}),
        ),
        frame(5, "state_replacement_committed", start),
    ] {
        writeln!(log, "{row}").unwrap();
    }
    let wm = p.with_file_name(format!("commit.{generation}.json"));
    let mut watermark: Value = serde_json::from_str(&fs::read_to_string(&wm).unwrap()).unwrap();
    watermark["through_seq"] = json!(5);
    watermark["through_event_id"] = json!(format!("{:032x}", 5));
    watermark["through_event_log_bytes"] = json!(fs::metadata(&p).unwrap().len());
    fs::write(&wm, watermark.to_string()).unwrap();
    let (_, r) = run(Agent::Fx, &p, &t.path().join("out"));
    let text = serde_json::to_string(&r).unwrap();
    assert!(!text.contains("SYNTHETIC_REPLACEMENT_SECRET_914"));
    assert!(!text.contains(&encoded));
    assert!(r.iter().any(|r| r["type"] == "gap"));
    assert!(r
        .iter()
        .any(|r| r.pointer("/content/0/text") == Some(&json!("The file contains an example."))));
    let broken = fs::read_to_string(&p)
        .unwrap()
        .replace(&hash, &"0".repeat(64));
    fs::write(&p, broken).unwrap();
    assert!(convert(&Options::new(Agent::Fx, p, t.path().join("bad"))).is_err());
}

#[test]
fn vibe_unified_generation_checks_digests_and_ignores_obsolete_generations() {
    use sha2::{Digest, Sha256};
    let t = tempfile::tempdir().unwrap();
    let root = t.path().join("store");
    let gen = root.join("generations/current");
    fs::create_dir_all(&gen).unwrap();
    let component = |path: &Path, v: Value| {
        let bytes = serde_json::to_vec(&v).unwrap();
        fs::write(path, [bytes.as_slice(), b"\n"].concat()).unwrap();
        json!({"path":path.file_name().unwrap().to_str().unwrap(),"sha256":format!("{:x}",Sha256::digest(&bytes))})
    };
    let checkpoint = component(
        &gen.join("checkpoint.json"),
        json!({"context":{"messages":[{"message":{"role":"user","content":[{"type":"text","text":"A checkpoint prompt"}]}},{"message":{"role":"assistant","content":[{"type":"tool_call","id":"c","name":"read","arguments":{"value":{"path":"a"}}}]}},{"message":{"role":"tool","tool_call_id":"c","outcome":"success","content":"native output"}}]}}),
    );
    let runtime = component(
        &gen.join("runtime.json"),
        json!({"session_metadata":{"cwd":"/work/app"}}),
    );
    let projection = component(
        &gen.join("projection.json"),
        json!({"snapshot":{"history":{"entries":[]}}}),
    );
    let mut manifest_value = json!({"session_id":"unified","generation":"current","snapshot_sequence":2,"checkpoint":checkpoint,"runtime_state":runtime,"projection_state":projection,"recovery_journal_segment":{"path":"journal.jsonl"}});
    let manifest = component(&gen.join("manifest.json"), manifest_value.clone());
    let mut current = json!({"store_format":"mistral.vibe.unified-session-store/v1","store_format_minor":10,"session_id":"unified","generation":"current","snapshot_sequence":2,"manifest_sha256":manifest["sha256"]});
    write(&root.join("CURRENT"), &[current.clone()]);
    write(
        &root.join("journal.jsonl"),
        &[json!({"kind":"native-recovery","sequence":3})],
    );
    write(
        &root.join("generations/obsolete/messages.jsonl"),
        &[json!({"role":"user","content":"obsolete"})],
    );
    fs::write(root.join("generations/obsolete/meta.json"), "{}").unwrap();
    let (s, r) = run(Agent::MistralVibe, &root, &t.path().join("out"));
    assert_eq!(s.sessions, 1);
    assert_eq!(r[0]["sessionId"], "unified");
    assert_eq!(r.iter().filter(|r| r["type"] == "tool_call").count(), 1);
    assert!(r
        .iter()
        .all(|r| r.pointer("/content/0/text") != Some(&json!("obsolete"))));
    manifest_value["checkpoint"] = component(
        &gen.join("checkpoint.json"),
        json!({"context":{"messages":[]}}),
    );
    let manifest = component(&gen.join("manifest.json"), manifest_value);
    current["manifest_sha256"] = manifest["sha256"].clone();
    write(&root.join("CURRENT"), &[current]);
    let (_, r) = run(Agent::MistralVibe, &root, &t.path().join("empty"));
    assert!(r[0]["missing"]
        .as_array()
        .unwrap()
        .contains(&json!("recovery_projection")));
    fs::write(gen.join("checkpoint.json"), "{}").unwrap();
    assert!(convert(&Options::new(
        Agent::MistralVibe,
        root,
        t.path().join("bad")
    ))
    .is_err());
}

#[test]
fn xum_preserves_archive_order_and_legacy_mux_identity() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path().join("sessions/native-workspace");
    write(
        &root.join("chat-archive.jsonl"),
        &[json!({"id":"archive","role":"user","parts":[{"type":"text","text":"older"}]})],
    );
    write(
        &root.join("chat.jsonl"),
        &[
            json!({"id":"active","role":"assistant","parts":[{"type":"text","text":"newer"},{"type":"dynamic-tool","toolCallId":"call","toolName":"read","input":{},"state":"output-available","output":"display"}]}),
        ],
    );
    let (_, rows) = run(Agent::Xum, &root, &tmp.path().join("xum"));
    assert_eq!(rows[0]["agent"]["name"], "xum");
    let messages: Vec<_> = rows.iter().filter(|r| r["type"] == "message").collect();
    assert_eq!(messages[0]["id"], "archive");
    assert_eq!(messages[1]["id"], "active");
    assert!(rows.iter().any(|r| r["_meta"]["com.coder.xum"].is_object()));
    let (_, legacy) = run(Agent::Mux, &root, &tmp.path().join("mux"));
    assert_eq!(legacy[0]["agent"]["name"], "mux");
    assert!(legacy
        .iter()
        .any(|r| r["_meta"]["com.coder.mux"].is_object()));
}
