//! Authored and adapted synthetic native evidence. Golden equality complements semantic assertions.
use asr_convert::{convert, Agent, Options};
use serde_json::{json, Value};
use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
    process::Command,
};
fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests")
}
fn read(path: &Path) -> Vec<Value> {
    fs::read_to_string(path)
        .unwrap()
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect()
}
fn validate(dir: &Path) {
    let output = Command::new("node")
        .arg(root().join("../../../tools/validator/bin/asr-validate.js"))
        .arg("--summary")
        .arg(dir)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{} {}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}
fn run(agent: Agent, input: PathBuf) -> (tempfile::TempDir, BTreeMap<String, Vec<Value>>) {
    let temp = tempfile::tempdir().unwrap();
    let out = temp.path().join("out");
    let summary = convert(&Options::new(agent, input, out.clone())).unwrap();
    assert!(summary.sessions > 0, "{agent:?}");
    validate(&out);
    let mut records = BTreeMap::new();
    for e in fs::read_dir(&out).unwrap() {
        let p = e.unwrap().path();
        records.insert(
            p.file_name().unwrap().to_str().unwrap().to_owned(),
            read(&p),
        );
    }
    (temp, records)
}
fn fixture(agent: Agent) -> (tempfile::TempDir, BTreeMap<String, Vec<Value>>) {
    run(agent, root().join("fixtures/jsonl-b").join(agent.name()))
}
fn one(agent: Agent) -> Vec<Value> {
    let (_t, map) = fixture(agent);
    assert_eq!(map.len(), 1);
    map.into_values().next().unwrap()
}
fn find<'a>(r: &'a [Value], kind: &str) -> &'a Value {
    r.iter().find(|r| r["type"] == kind).unwrap()
}
fn synthetic(agent: Agent, rows: &[Value]) -> Vec<Value> {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("session.jsonl");
    fs::write(
        &path,
        rows.iter().map(|r| format!("{r}\n")).collect::<String>(),
    )
    .unwrap();
    let (_temp, r) = run(agent, path);
    r.into_values().next().unwrap()
}
#[test]
fn all_batch_goldens_match_and_reexport_exactly() {
    for agent in [
        Agent::Antigravity,
        Agent::Tabnine,
        Agent::Qoder,
        Agent::Droid,
        Agent::CopilotCli,
        Agent::QwenCode,
        Agent::GrokBuild,
        Agent::Pi,
        Agent::KimiCode,
        Agent::DeepSeekHarness,
        Agent::Junie,
        Agent::OpenClaw,
    ] {
        let (temp, data) = fixture(agent);
        let golden = root().join("jsonl-b/golden").join(agent.name());
        if std::env::var_os("ASR_UPDATE_JSONL_B_GOLDENS").is_some() {
            fs::create_dir_all(&golden).unwrap();
            for name in data.keys() {
                fs::copy(temp.path().join("out").join(name), golden.join(name)).unwrap();
            }
        }
        assert_eq!(fs::read_dir(&golden).unwrap().count(), data.len());
        for name in data.keys() {
            assert_eq!(
                fs::read(temp.path().join("out").join(name)).unwrap(),
                fs::read(golden.join(name)).unwrap(),
                "{} golden",
                agent.name()
            );
        }
        convert(&Options::new(
            agent,
            root().join("fixtures/jsonl-b").join(agent.name()),
            temp.path().join("out"),
        ))
        .unwrap();
        for (name, rows) in data {
            assert_eq!(rows, read(&temp.path().join("out").join(name)));
        }
    }
}
#[test]
fn copilot_separates_children_and_keeps_recorded_outcome() {
    let (_t, rows) = fixture(Agent::CopilotCli);
    assert_eq!(rows.len(), 2);
    let parent = rows
        .values()
        .find(|r| r[0]["sessionId"] == "complete-copilot")
        .unwrap();
    let child = rows
        .values()
        .find(|r| r[0]["sessionId"] == "worker")
        .unwrap();
    assert_eq!(child[0]["namespace"], "complete-copilot");
    assert_eq!(
        child[0]["parent"]["session"],
        "copilot-cli:complete-copilot"
    );
    assert!(!parent.iter().any(|r| r["id"] == "child-answer"));
    assert_eq!(find(parent, "tool_result")["status"], "failed");
    assert_eq!(find(parent, "tool_result")["exec"]["exitCode"], 0);
    assert_eq!(
        find(parent, "tool_result")["content"][0]["text"],
        "model text"
    );
    assert_eq!(
        parent.iter().filter(|r| r["type"] == "tool_call").count(),
        1
    );
    assert_eq!(
        parent.iter().filter(|r| r["type"] == "inference").count(),
        1
    );
    let inf = find(parent, "inference");
    assert_eq!(inf["model"]["id"], "served");
    assert_eq!(inf["usage"]["outputTokens"], 0);
    assert!(inf["usage"].get("inputTokens").is_none());
    assert_eq!(find(parent, "approval")["scope"], "session");
}
#[test]
fn anthropic_style_journals_do_not_guess_model_calls_or_human_authorship() {
    for agent in [Agent::Droid, Agent::Qoder] {
        let rows = one(agent);
        assert!(!rows.iter().any(|r| r["type"] == "inference"));
        assert_eq!(find(&rows, "tool_call")["requestedBy"], "model");
        let prompt = rows
            .iter()
            .find(|r| r["type"] == "message" && r["role"] == "user")
            .unwrap();
        assert!(prompt.get("author").is_none());
    }
    let qoder = one(Agent::Qoder);
    assert_eq!(
        find(&qoder, "tool_result")["content"][0]["text"],
        "model text"
    );
    assert!(one(Agent::Droid).iter().any(|r| r["type"] == "gap"));
}
#[test]
fn tabnine_uses_last_snapshot_and_keeps_raw_output_out_of_content() {
    let r = one(Agent::Tabnine);
    let answer = r.iter().find(|r| r["id"] == "answer").unwrap();
    assert_eq!(answer["content"][0]["text"], "final");
    assert_eq!(r.iter().filter(|r| r["id"] == "answer").count(), 1);
    let result = find(&r, "tool_result");
    assert_eq!(result["status"], "completed");
    assert!(result.get("content").is_none());
    assert!(!r.iter().any(|r| r["type"] == "inference"));
}
#[test]
fn kimi_keeps_completed_parts_and_folds_request_usage_at_completion() {
    let r = one(Agent::KimiCode);
    assert_eq!(r[0]["sessionId"], "synthetic-session");
    assert!(r[0].get("namespace").is_none());
    assert_eq!(r[0]["cwd"], "/work/app");
    let msg = r
        .iter()
        .find(|r| r["type"] == "message" && r["role"] == "assistant")
        .unwrap();
    assert_eq!(msg["content"][0]["text"], "a ");
    assert!(r.iter().any(|r| r["content"][0]["text"] == "b"));
    assert_eq!(r.iter().filter(|r| r["type"] == "inference").count(), 1);
    let inf = find(&r, "inference");
    assert_eq!(inf["model"]["requested"], "requested");
    assert!(inf["model"].get("id").is_none());
    assert_eq!(inf["usage"]["inputTokens"], 15);
    assert_eq!(inf["usage"]["outputTokens"], 0);
    assert_eq!(inf["ts"], "2023-11-14T22:13:23.000Z");
    assert!(
        r.iter().position(|r| r["type"] == "tool_call").unwrap()
            < r.iter().position(|r| r["type"] == "inference").unwrap()
    );
    assert!(find(&r, "tool_result").get("content").is_none());
}
#[test]
fn grok_joins_adjacent_chunks_and_preserves_completion_position() {
    let r = one(Agent::GrokBuild);
    let m = find(&r, "message");
    assert_eq!(m["content"][0]["text"], "a b");
    assert_eq!(m["inferenceId"], "response-1");
    let inf = find(&r, "inference");
    assert_eq!(inf["id"], "response-1");
    assert_eq!(inf["usage"]["inputTokens"], 12);
    assert_eq!(inf["ts"], "2023-11-14T22:13:25.000Z");
    assert!(
        r.iter().position(|r| r["type"] == "inference").unwrap()
            > r.iter().position(|r| r["type"] == "tool_result").unwrap()
    );
    assert!(find(&r, "tool_result").get("content").is_none());
}
#[test]
fn pi_and_openclaw_do_not_promote_requested_models_to_served() {
    for agent in [Agent::Pi, Agent::OpenClaw] {
        let r = one(agent);
        let inf = find(&r, "inference");
        if agent == Agent::Pi {
            assert!(inf["model"].get("id").is_none());
        } else {
            assert_eq!(inf["model"]["id"], "served");
            assert_eq!(inf["usage"]["inputTokens"], 15);
            assert_eq!(inf["usage"]["outputTokens"], 0);
            let user = r
                .iter()
                .find(|r| r["type"] == "message" && r["role"] == "user")
                .unwrap();
            assert_eq!(user["content"], json!([]));
        }
        assert!(inf["model"]["requested"].is_string());
    }
}
#[test]
fn remaining_agents_keep_native_evidence_and_conservative_core_fields() {
    let a = one(Agent::Antigravity);
    assert_eq!(a[0]["sessionId"], "synthetic-conversation");
    assert_eq!(find(&a, "tool_call")["input"]["path"], "hello.txt");
    assert!(find(&a, "message")["content"][0]
        .get("visibility")
        .is_none());
    let q = one(Agent::QwenCode);
    assert_eq!(find(&q, "tool_call")["callId"], "call-1");
    assert_eq!(find(&q, "session_info")["title"], "Synthetic title");
    let j = one(Agent::Junie);
    assert!(j
        .iter()
        .filter(|r| r["type"] == "file_change")
        .all(|r| r["status"] == "unknown"));
    assert!(j.iter().any(|r| r["type"] == "file_change"
        && r["before"]["text"].is_string()
        && r["after"]["text"].is_string()));
    let d = one(Agent::DeepSeekHarness);
    assert!(d.iter().any(|r| r["type"] == "tool_call"));
    assert!(d.iter().any(|r| r["type"] == "tool_result"));
}
#[test]
fn repeated_calls_stay_ambiguous_and_results_fold_once() {
    let r = synthetic(
        Agent::Droid,
        &[
            json!({"type":"session_start","sessionId":"duplicate"}),
            json!({"type":"message","id":"one","role":"assistant","content":[{"type":"tool_use","id":"same","name":"Read","input":{}}]}),
            json!({"type":"message","id":"two","role":"assistant","content":[{"type":"tool_use","id":"same","name":"Read","input":{}}]}),
            json!({"type":"message","role":"user","content":[{"type":"tool_result","tool_use_id":"same","is_error":true,"content":"first"}]}),
            json!({"type":"message","role":"user","content":[{"type":"tool_result","tool_use_id":"same","is_error":false,"content":"last"}]}),
        ],
    );
    assert_eq!(r.iter().filter(|r| r["type"] == "tool_call").count(), 2);
    assert_eq!(r.iter().filter(|r| r["type"] == "tool_result").count(), 1);
    assert_eq!(find(&r, "tool_result")["content"][0]["text"], "last");
}
#[test]
fn safety_large_values_null_and_source_recovery() {
    let secret = "synthetic-private-answer";
    let r = synthetic(
        Agent::Droid,
        &[
            json!({"type":"session_start","sessionId":"safety","api_key":secret}),
            json!({"type":"message","id":"row","role":"assistant","content":[{"type":"thinking","thinking":"visible","signature":"opaque-secret"},{"type":"tool_use","id":"call","name":"Read","input":{"n":9007199254740993u64,"value":secret,"null":null}}]}),
        ],
    );
    let text = serde_json::to_string(&r).unwrap();
    assert!(!text.contains(secret));
    assert!(!text.contains("opaque-secret"));
    let call = find(&r, "tool_call");
    assert_eq!(call["input"]["n"], "9007199254740993");
    assert_eq!(call["input"]["null"], Value::Null);
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("broken.jsonl");
    fs::write(&path,"{\"type\":\"session_start\",\"sessionId\":\"broken\"}\n{invalid}\n{\"type\":\"message\",\"role\":\"user\",\"content\":\"after\"}\n{\"type\":").unwrap();
    let out = tmp.path().join("out");
    let summary = convert(&Options::new(Agent::Droid, path, out.clone())).unwrap();
    assert_eq!(summary.diagnostics["unparseable_source_line"], 1);
    assert_eq!(summary.diagnostics["incomplete_source_tail"], 1);
    validate(&out);
}
#[test]
fn copilot_reused_native_call_ids_keep_both_requests() {
    let r = synthetic(
        Agent::CopilotCli,
        &[
            json!({"type":"session.start","data":{"sessionId":"duplicate"}}),
            json!({"type":"tool.execution_start","id":"first","data":{"toolCallId":"same","toolName":"view","arguments":{}}}),
            json!({"type":"tool.execution_start","id":"second","data":{"toolCallId":"same","toolName":"view","arguments":{}}}),
            json!({"type":"tool.execution_complete","data":{"toolCallId":"same","success":true}}),
        ],
    );
    assert_eq!(r.iter().filter(|r| r["type"] == "tool_call").count(), 2);
}
#[test]
fn deepseek_generations_and_copied_seed_are_native_evidence() {
    let tmp = tempfile::tempdir().unwrap();
    let old = json!({"type":"session","id":"old-generation","version":4});
    let current = json!({"type":"session","id":"child","version":4,"parentSession":"parent","origin":"subagent","seedLength":2});
    fs::write(tmp.path().join("session.jsonl"), format!("{old}\n")).unwrap();
    fs::write(tmp.path().join("session.v1.jsonl"),format!("{current}\n{}\n{}\n",json!({"type":"user/message","seq":1,"data":{"id":"copy","role":"user","source":{"kind":"user"},"content":"inherited"}}),json!({"type":"user/message","seq":2,"data":{"id":"own","role":"user","source":{"kind":"user"},"content":"new"}}))).unwrap();
    let (_out, map) = run(Agent::DeepSeekHarness, tmp.path().to_owned());
    assert_eq!(map.len(), 1);
    let r = map.into_values().next().unwrap();
    assert_eq!(r[0]["sessionId"], "child");
    assert_eq!(r[0]["parent"]["kind"], "subagent");
    assert_eq!(
        r.iter().find(|r| r["id"] == "copy").unwrap()["copiedFrom"]["session"],
        "deepseek-harness:parent"
    );
    assert!(r
        .iter()
        .find(|r| r["id"] == "own")
        .unwrap()
        .get("copiedFrom")
        .is_none());
}
#[test]
fn unknown_identity_is_not_replaced_with_a_filename() {
    for agent in [
        Agent::Droid,
        Agent::Qoder,
        Agent::QwenCode,
        Agent::Pi,
        Agent::Tabnine,
        Agent::OpenClaw,
    ] {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("looks-like-a-session-id.jsonl");
        fs::write(
            &path,
            "{\"type\":\"user\",\"content\":\"no recorded identity\"}\n",
        )
        .unwrap();
        let summary = convert(&Options::new(agent, path, tmp.path().join("out"))).unwrap();
        assert_eq!(summary.sessions, 0, "{agent:?}");
        assert_eq!(summary.diagnostics["unidentified_source"], 1);
    }
}
#[test]
fn source_location_and_compression_do_not_change_bytes() {
    let tmp = tempfile::tempdir().unwrap();
    let fixture = root().join("fixtures/jsonl-b/droid/session.jsonl");
    let bytes = fs::read(&fixture).unwrap();
    let compressed = tmp.path().join("relocated.jsonl.zst");
    fs::write(
        &compressed,
        zstd::stream::encode_all(bytes.as_slice(), 1).unwrap(),
    )
    .unwrap();
    let (a, original) = run(Agent::Droid, fixture);
    let (b, moved) = run(Agent::Droid, compressed);
    assert_eq!(original, moved);
    for name in original.keys() {
        assert_eq!(
            fs::read(a.path().join("out").join(name)).unwrap(),
            fs::read(b.path().join("out").join(name)).unwrap()
        );
    }
}
#[test]
fn grok_reused_call_ids_remain_ambiguous_and_encrypted_reasoning_has_no_content() {
    let r = synthetic(
        Agent::GrokBuild,
        &[
            json!({"sessionId":"grok-duplicate","update":{"sessionUpdate":"tool_call","toolCallId":"same","name":"Read","rawInput":{"path":"a"}}}),
            json!({"sessionId":"grok-duplicate","update":{"sessionUpdate":"tool_call","toolCallId":"same","name":"Read","rawInput":{"path":"b"}}}),
            json!({"sessionId":"grok-duplicate","update":{"sessionUpdate":"tool_call_update","toolCallId":"same","status":"completed","rawInput":{"path":"ambiguous"}}}),
        ],
    );
    let calls: Vec<_> = r.iter().filter(|r| r["type"] == "tool_call").collect();
    assert_eq!(calls.len(), 2);
    assert_eq!(calls[0]["input"]["path"], "a");
    assert_eq!(calls[1]["input"]["path"], "b");
    let r = synthetic(
        Agent::Pi,
        &[
            json!({"type":"session","version":3,"id":"encrypted"}),
            json!({"type":"message","id":"reasoning","message":{"role":"assistant","content":[{"type":"thinking","redacted":true,"thinking":"opaque-body","thinkingSignature":"opaque-signature"}]}}),
        ],
    );
    let part = &find(&r, "message")["content"][0];
    assert_eq!(part["visibility"], "encrypted");
    assert!(part.get("text").is_none());
    assert!(!serde_json::to_string(&r).unwrap().contains("opaque-body"));
}
#[test]
fn ordinary_message_times_do_not_establish_session_start() {
    let r = synthetic(
        Agent::QwenCode,
        &[
            json!({"type":"user","sessionId":"times","uuid":"user","timestamp":"2026-11-01T00:00:00Z","message":{"role":"user","parts":[{"text":"hello"}]}}),
        ],
    );
    assert!(r[0].get("startedAt").is_none());
    assert_eq!(find(&r, "message")["ts"], "2026-11-01T00:00:00Z");
}

#[test]
fn invalid_cache_counts_do_not_become_zero_in_input_totals() {
    for cache_read in [json!(9007199254740993u64), json!(null), json!(-1)] {
        let r = synthetic(
            Agent::Pi,
            &[
                json!({"type":"session","version":3,"id":"invalid-count"}),
                json!({"type":"message","id":"answer","message":{"role":"assistant","responseId":"response","content":"answer","usage":{"input":10,"output":0,"cacheRead":cache_read,"cacheWrite":0}}}),
            ],
        );
        let u = &find(&r, "inference")["usage"];
        assert!(u.get("inputTokens").is_none());
        assert!(u.get("cacheReadTokens").is_none());
        assert_eq!(u["cacheWriteTokens"], 0);
        assert_eq!(u["outputTokens"], 0);
    }
    let r = synthetic(
        Agent::Pi,
        &[
            json!({"type":"session","version":3,"id":"optional-count"}),
            json!({"type":"message","id":"answer","message":{"role":"assistant","responseId":"response","content":"answer","usage":{"input":10,"output":0}}}),
        ],
    );
    let u = &find(&r, "inference")["usage"];
    assert_eq!(u["inputTokens"], 10);
    assert!(u.get("cacheReadTokens").is_none());
}

#[test]
fn openclaw_injected_and_inter_session_messages_override_human_sender_metadata() {
    for (kind, author, origin) in [
        ("internal_system", "harness", "injected"),
        ("inter_session", "agent", "subagent_report"),
    ] {
        let rows = synthetic(
            Agent::OpenClaw,
            &[
                json!({"type":"session","version":3,"id":"injected-author"}),
                json!({"type":"message","id":"injected","message":{"role":"user","content":"native text","provenance":{"kind":kind},"__openclaw":{"senderIdentity":{"type":"profile","senderKind":"human"},"modelPromptProjection":{"text":"native text"}}}}),
            ],
        );
        let message = find(&rows, "message");
        assert_eq!(message["author"], author);
        assert_eq!(message["origin"], origin);
    }
}

#[test]
fn kimi_protocol_15_uses_native_state_identity_and_completed_part_order() {
    let tmp = tempfile::tempdir().unwrap();
    let session = tmp.path().join("arbitrary-directory");
    let agent = session.join("agents/main");
    fs::create_dir_all(&agent).unwrap();
    fs::write(
        session.join("state.json"),
        r#"{"id":"native-kimi","forkedFrom":"prior-kimi","cwd":"/work/app"}"#,
    )
    .unwrap();
    let fixture = root().join("../../../upstream/kimi-code/samples/native/native.jsonl");
    let mut wire = fs::read_to_string(fixture).unwrap();
    wire.push_str("{broken}\n{partial");
    fs::write(agent.join("wire.jsonl"), &wire).unwrap();
    let (_out, streams) = run(Agent::KimiCode, session.clone());
    let rows = streams.into_values().next().unwrap();
    assert_eq!(rows[0]["sessionId"], "native-kimi");
    assert!(rows[0].get("namespace").is_none());
    assert_eq!(rows[0]["parent"]["session"], "kimi-code:prior-kimi");
    assert_eq!(rows[0]["startedAt"], "2026-10-30T12:00:00.000Z");
    assert_eq!(
        rows.iter().find(|r| r["id"] == "prompt-1").unwrap()["content"][0]["text"],
        "Exact\r\n"
    );
    assert!(rows
        .iter()
        .any(|r| r["content"][0]["visibility"] == "encrypted"));
    assert!(!serde_json::to_string(&rows)
        .unwrap()
        .contains("SYNTHETIC-OPAQUE"));
    let call = find(&rows, "tool_call");
    assert_eq!(call["input"]["n"], "9007199254740993");
    assert!(rows
        .iter()
        .any(|r| r["type"] == "gap" && r["reason"] == "unparseable"));
    assert!(rows
        .iter()
        .any(|r| r["type"] == "gap" && r["reason"] == "not_retained"));
    fs::write(agent.join("wire.jsonl"), wire.replace("\"1.5\"", "\"1.4\"")).unwrap();
    assert!(convert(&Options::new(
        Agent::KimiCode,
        session.clone(),
        tmp.path().join("unsupported")
    ))
    .is_err());
    fs::write(agent.join("wire.jsonl"), "{\"type\":\"metadata\",\"protocol_version\":\"1.5\"}\n{\"type\":\"context.append_loop_event\",\"event\":{\"type\":\"content.part\",\"uuid\":\"completed-a\",\"stepUuid\":\"same-step\",\"part\":{\"type\":\"text\",\"text\":\"first\"}}}\n{\"type\":\"context.append_message\",\"message\":{\"id\":\"notice\",\"role\":\"user\",\"origin\":{\"kind\":\"injection\"},\"content\":\"notice\"}}\n{\"type\":\"context.append_loop_event\",\"event\":{\"type\":\"content.part\",\"uuid\":\"completed-b\",\"stepUuid\":\"same-step\",\"part\":{\"type\":\"text\",\"text\":\"last\"}}}\n").unwrap();
    let (_out, streams) = run(Agent::KimiCode, session);
    let rows = streams.into_values().next().unwrap();
    let messages: Vec<_> = rows.iter().filter(|r| r["type"] == "message").collect();
    assert_eq!(
        messages
            .iter()
            .map(|r| r["id"].as_str().unwrap())
            .collect::<Vec<_>>(),
        ["completed-a", "notice", "completed-b"]
    );
    assert_eq!(messages[1]["origin"], "injected");
}

#[test]
fn kimi_child_identity_and_result_folding_keep_native_relationships() {
    let tmp = tempfile::tempdir().unwrap();
    let session = tmp.path().join("unrelated-directory");
    let child = session.join("agents/child");
    fs::create_dir_all(&child).unwrap();
    fs::write(
        session.join("state.json"),
        r#"{"id":"session-native","agents":{"child":{"labels":{"parentAgentId":"main"}}}}"#,
    )
    .unwrap();
    let wire = [
        json!({"type":"metadata","protocol_version":"1.5"}),
        json!({"type":"context.append_loop_event","time":1793361600001u64,"event":{"type":"tool.call","uuid":"native-call","toolCallId":"c","name":"read","args":{}}}),
        json!({"type":"context.append_loop_event","time":1793361600002u64,"event":{"type":"tool.result","toolCallId":"c","result":{"output":"old","isError":false}}}),
        json!({"type":"context.append_message","message":{"id":"intervening","role":"user","content":"notice"}}),
        json!({"type":"context.append_loop_event","time":1793361600003u64,"event":{"type":"tool.result","toolCallId":"c","result":{"output":"final","isError":true}}}),
    ].iter().map(|row| format!("{row}\n")).collect::<String>();
    fs::write(child.join("wire.jsonl"), wire).unwrap();
    let (_out, streams) = run(Agent::KimiCode, session);
    let rows = streams.into_values().next().unwrap();
    assert_eq!(rows[0]["sessionId"], "child");
    assert_eq!(rows[0]["namespace"], "session-native");
    assert_eq!(rows[0]["parent"]["session"], "kimi-code:session-native");
    assert_eq!(find(&rows, "tool_call")["id"], "native-call");
    let results: Vec<_> = rows.iter().filter(|r| r["type"] == "tool_result").collect();
    assert_eq!(results.len(), 1);
    assert_eq!(results[0]["status"], "failed");
    assert_eq!(results[0]["ts"], "2026-10-30T12:00:00.003Z");
    assert!(
        rows.iter().position(|r| r["id"] == "intervening").unwrap()
            < rows
                .iter()
                .position(|r| r["type"] == "tool_result")
                .unwrap()
    );
    assert!(rows[0]["missing"]
        .as_array()
        .unwrap()
        .contains(&json!("copies")));
}

#[test]
fn kimi_rejects_a_store_without_native_session_identity() {
    let temporary = tempfile::tempdir().unwrap();
    let session = temporary.path().join("directory-is-not-an-id");
    let agent = session.join("agents/main");
    fs::create_dir_all(&agent).unwrap();
    fs::write(
        agent.join("wire.jsonl"),
        "{\"type\":\"metadata\",\"protocol_version\":\"1.5\"}\n",
    )
    .unwrap();
    let output = temporary.path().join("output");
    let error = convert(&Options::new(Agent::KimiCode, session, output.clone())).unwrap_err();
    assert!(error.to_string().contains("source_staging_failed"));
    assert!(!fs::read_dir(output).unwrap().any(|entry| {
        entry
            .unwrap()
            .path()
            .extension()
            .is_some_and(|extension| extension == "jsonl")
    }));
}
