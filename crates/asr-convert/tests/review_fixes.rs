//! Synthetic source-to-record regressions for edit and provenance evidence.
use asr_convert::{convert, Agent, Options, Summary};
use rusqlite::{params, Connection};
use serde_json::{json, Value};
use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
};

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}
fn write(path: &Path, rows: &[Value]) {
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(
        path,
        rows.iter().map(|v| format!("{v}\n")).collect::<String>(),
    )
    .unwrap();
}
fn validate(path: &Path) {
    let result = Command::new("node")
        .arg(root().join("tools/validator/bin/asr-validate.js"))
        .args(["--json", "--summary"])
        .arg(path)
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "{} {}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
}
fn read(out: &Path) -> Vec<Value> {
    let mut paths: Vec<_> = fs::read_dir(out)
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| p.extension().is_some_and(|x| x == "jsonl"))
        .collect();
    paths.sort();
    paths
        .into_iter()
        .flat_map(|p| {
            fs::read_to_string(p)
                .unwrap()
                .lines()
                .map(|line| serde_json::from_str(line).unwrap())
                .collect::<Vec<Value>>()
        })
        .collect()
}
fn run(agent: Agent, rows: &[Value]) -> (tempfile::TempDir, Summary, Vec<Value>) {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("native.jsonl");
    write(&path, rows);
    let out = temp.path().join("out");
    let summary = convert(&Options::new(agent, path, out.clone())).unwrap();
    validate(&out);
    let rows = read(&out);
    (temp, summary, rows)
}
fn tool(name: &str, input: Value, output: Value, error: Option<bool>) -> Vec<Value> {
    let mut result =
        json!({"type":"tool_result","tool_use_id":"edit","content":"Recorded result."});
    if let Some(error) = error {
        result["is_error"] = json!(error);
    }
    let mut row =
        json!({"type":"user","uuid":"result","sessionId":"edits","message":{"content":[result]}});
    if !output.is_null() {
        row["toolUseResult"] = output;
    }
    vec![
        json!({"type":"assistant","uuid":"request","sessionId":"edits","cwd":"/work/app","message":{"id":"response","model":"example-model","content":[{"type":"tool_use","id":"edit","name":name,"input":input}]}}),
        row,
    ]
}
fn change(rows: &[Value]) -> &Value {
    rows.iter().find(|r| r["type"] == "file_change").unwrap()
}

#[test]
fn claude_structured_edits_preserve_success_full_states_and_replacements() {
    let (_, summary, rows) = run(
        Agent::ClaudeCode,
        &tool(
            "Edit",
            json!({"file_path":"file.txt","old_string":"old\n","new_string":"new\n"}),
            json!({"filePath":"file.txt","oldString":"old\n","newString":"new\n","originalFile":"old\n","structuredPatch":[]}),
            None,
        ),
    );
    assert!(!summary.diagnostics.contains_key("record_shape"));
    assert_eq!(change(&rows)["op"], "modify");
    assert_eq!(change(&rows)["status"], "applied");
    assert_eq!(change(&rows)["before"]["text"], "old\n");
    assert_eq!(
        change(&rows)["edits"],
        json!([{"oldText":"old\n","newText":"new\n"}])
    );
    assert!(change(&rows).get("patch").is_none());
    let (_, _, rows) = run(
        Agent::ClaudeCode,
        &tool(
            "MultiEdit",
            json!({"file_path":"file.txt"}),
            json!({"filePath":"file.txt","edits":[{"old_string":"","new_string":"one"},{"old_string":"two","new_string":""}]}),
            None,
        ),
    );
    assert_eq!(
        change(&rows)["edits"],
        json!([{"oldText":"","newText":"one"},{"oldText":"two","newText":""}])
    );
    let (_, _, rows) = run(
        Agent::ClaudeCode,
        &tool(
            "Write",
            json!({"file_path":"file.txt","content":"requested"}),
            json!({"filePath":"file.txt","type":"update","content":"actual","originalFile":"before"}),
            None,
        ),
    );
    assert_eq!(change(&rows)["before"]["text"], "before");
    assert_eq!(change(&rows)["after"]["text"], "actual");
}

#[test]
fn claude_input_edits_require_success_and_staged_changes_remain_proposed() {
    for (error, output, status, has_edits) in [
        (Some(false), Value::Null, "applied", true),
        (Some(true), Value::Null, "failed", false),
        (None, Value::Null, "unknown", false),
        (
            None,
            json!({"filePath":"file.txt","staged":true}),
            "proposed",
            false,
        ),
        (
            Some(false),
            json!({"filePath":"file.txt","interrupted":true}),
            "unknown",
            false,
        ),
    ] {
        let (_, _, rows) = run(
            Agent::ClaudeCode,
            &tool(
                "Edit",
                json!({"file_path":"file.txt","old_string":"a","new_string":"b"}),
                output,
                error,
            ),
        );
        assert_eq!(change(&rows)["status"], status);
        assert_eq!(change(&rows).get("edits").is_some(), has_edits);
    }
    let (_, _, rows) = run(
        Agent::ClaudeCode,
        &tool(
            "Write",
            json!({"file_path":"file.txt","content":"new\n"}),
            json!({"filePath":"file.txt","type":"create","content":"new\n","originalFile":null}),
            None,
        ),
    );
    assert_eq!(change(&rows)["op"], "add");
    assert!(change(&rows).get("before").is_none());
}

#[test]
fn claude_prompt_authorship_is_explicit_and_sdk_input_stays_unknown() {
    let variants = [
        (
            json!({"origin":{"kind":"human"}}),
            Some("human"),
            Some("prompt"),
        ),
        (
            json!({"origin":{"kind":"human","queued":true}}),
            Some("human"),
            Some("queued"),
        ),
        (
            json!({"isMeta":true,"origin":{"kind":"human"}}),
            Some("harness"),
            Some("injected"),
        ),
        (
            json!({"turnOrigin":"sdk","userType":"external"}),
            None,
            None,
        ),
        (json!({"turnOrigin":"sdk","promptSource":"sdk"}), None, None),
        (
            json!({"origin":{"kind":"scheduled"}}),
            None,
            Some("scheduled"),
        ),
        (
            json!({"origin":{"kind":"peer","fromSession":"parent"}}),
            Some("agent"),
            Some("subagent_report"),
        ),
    ];
    for (extra, author, origin) in variants {
        let mut row = json!({"type":"user","uuid":"prompt","sessionId":"authors","message":{"content":"Example prompt."}});
        row.as_object_mut()
            .unwrap()
            .extend(extra.as_object().unwrap().clone());
        let (_, _, rows) = run(Agent::ClaudeCode, &[row]);
        let r = rows.iter().find(|r| r["type"] == "message").unwrap();
        assert_eq!(r["author"].as_str(), author);
        assert_eq!(r["origin"].as_str(), origin);
    }
}

#[test]
fn claude_tool_kinds_follow_its_published_map() {
    for (name, kind) in [
        ("NotebookEdit", "edit"),
        ("PowerShell", "execute"),
        ("ToolSearch", "search"),
        ("WebSearch", "fetch"),
        ("unknown", "other"),
    ] {
        let (_, _, rows) = run(
            Agent::ClaudeCode,
            &tool(name, json!({}), Value::Null, Some(false)),
        );
        assert_eq!(
            rows.iter().find(|r| r["type"] == "tool_call").unwrap()["kind"],
            kind
        );
    }
}

#[test]
fn claude_served_tier_does_not_overwrite_requested_settings() {
    let (_, _, rows) = run(
        Agent::ClaudeCode,
        &[
            json!({"type":"api-request","id":"request","sessionId":"tiers","params":{"service_tier":"auto"}}),
            json!({"type":"assistant","sessionId":"tiers","requestRef":"request","message":{"id":"response","model":"example","usage":{"input_tokens":1,"output_tokens":1,"service_tier":"priority"}}}),
        ],
    );
    let r = rows.iter().find(|r| r["type"] == "inference").unwrap();
    assert_eq!(r["settings"]["serviceTier"], "auto");
    assert_eq!(
        r["_meta"]["com.anthropic.claude-code"]["servedServiceTier"],
        "priority"
    );
}

#[test]
fn codex_cancellation_sandbox_and_recorded_response_links_stay_distinct() {
    let (_, _, rows) = run(
        Agent::Codex,
        &[
            json!({"type":"session_meta","payload":{"id":"codex-facts"}}),
            json!({"type":"turn_context","payload":{"turn_id":"t","sandbox_policy":{"type":"workspace-write"}}}),
            json!({"type":"response_item","payload":{"type":"function_call","id":"call","response_id":"response","call_id":"run","name":"exec_command","arguments":"{}"}}),
            json!({"type":"event_msg","payload":{"type":"exec_command_end","call_id":"run","status":"cancelled"}}),
            json!({"type":"response_item","payload":{"type":"message","id":"answer","role":"assistant","response_id":"response","content":[{"type":"output_text","text":"Done."}]}}),
            json!({"type":"token_usage_record","payload":{"response_id":"response","model":"example"}}),
            json!({"type":"turn_context","payload":{"sandbox_policy":{"type":"external-sandbox"}}}),
        ],
    );
    assert_eq!(
        rows.iter().find(|r| r["type"] == "tool_result").unwrap()["status"],
        "cancelled"
    );
    let settings: Vec<_> = rows
        .iter()
        .filter(|r| r["type"] == "session_info")
        .collect();
    assert!(settings[0]["agentSettings"]
        .get("externalSandbox")
        .is_none());
    assert_eq!(
        settings[1]["agentSettings"]["externalSandbox"]["source"],
        "setting"
    );
    for id in ["call", "answer"] {
        assert_eq!(
            rows.iter().find(|r| r["id"] == id).unwrap()["inferenceId"],
            "response"
        );
    }
}

#[test]
fn reasoning_summaries_empty_thinking_and_opaque_blocks_are_honest() {
    let (_, _, rows) = run(
        Agent::ClaudeCode,
        &[
            json!({"type":"assistant","sessionId":"reasoning","message":{"id":"response","model":"example","content":[{"type":"thinking","thinking":"A summary.","signature":"opaque"},{"type":"thinking","thinking":""},{"type":"thinking","signature":"opaque"},{"type":"redacted_thinking","data":"opaque"}]}}),
        ],
    );
    let parts = &rows.iter().find(|r| r["type"] == "message").unwrap()["content"];
    assert_eq!(
        parts[0],
        json!({"type":"reasoning","visibility":"summary","summary":["A summary."]})
    );
    for i in [1, 2] {
        assert_eq!(parts[i], json!({"type":"reasoning","visibility":"omitted"}));
    }
    assert_eq!(
        parts[3],
        json!({"type":"reasoning","visibility":"encrypted"})
    );
    assert!(!serde_json::to_string(&rows).unwrap().contains("opaque"));
}

#[test]
fn bad_records_become_gaps_and_bad_sessions_leave_good_sessions_available() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("native");
    write(
        &input.join("a.jsonl"),
        &tool(
            "Bash",
            json!({"command":"example"}),
            json!({"exitCode":"not-an-integer"}),
            Some(false),
        ),
    );
    write(
        &input.join("b.jsonl"),
        &[
            json!({"type":"user","sessionId":"good","uuid":"good-prompt","message":{"content":"Kept."}}),
        ],
    );
    let out = temp.path().join("out");
    let summary = convert(&Options::new(Agent::ClaudeCode, input, out.clone())).unwrap();
    assert_eq!(
        summary.session_diagnostics["claude-code:edits"]["record_shape"],
        1
    );
    assert_eq!(summary.sessions, 2);
    validate(&out);
    let rows = read(&out);
    assert!(rows.iter().any(|r| r["id"] == "good-prompt"));
    assert!(rows
        .iter()
        .any(|r| r["type"] == "gap" && r["reason"] == "unparseable"));
    let header = rows.iter().find(|r| r["sessionId"] == "edits").unwrap();
    assert!(header["missing"]
        .as_array()
        .unwrap()
        .contains(&json!("record_shape")));
}

#[test]
fn repository_facts_are_recorded_without_filesystem_or_conversion_time_git() {
    for (agent, rows) in [
        (
            Agent::ClaudeCode,
            vec![
                json!({"type":"user","sessionId":"repo","cwd":"/work/nonexistent","gitBranch":"recorded-branch","message":{"content":"Example."}}),
            ],
        ),
        (
            Agent::Codex,
            vec![
                json!({"type":"session_meta","payload":{"id":"repo","cwd":"/work/nonexistent","git":{"commit_hash":"a".repeat(40),"branch":"recorded-branch","repository_url":"https://example.com/team/repo.git"}}}),
            ],
        ),
    ] {
        let (_, _, result) = run(agent, &rows);
        assert_eq!(result[0]["cwd"], "/work/nonexistent");
        assert_eq!(result[0]["repos"][0]["path"], "/work/nonexistent");
        assert_eq!(result[0]["repos"][0]["branch"], "recorded-branch");
        if agent == Agent::Codex {
            assert_eq!(result[0]["repos"][0]["head"], "a".repeat(40));
        }
    }
    let (_, _, rows) = run(
        Agent::Codex,
        &[json!({"type":"session_meta","payload":{"id":"no-git","cwd":"/work/no-git"}})],
    );
    assert!(rows[0].get("repos").is_none());
    let (_, _, rows) = run(
        Agent::Codex,
        &[
            json!({"type":"session_meta","payload":{"id":"unsafe-git","cwd":"/work/no-git","git":{"commit_hash":"short","repository_url":"https://name:password@example.com/repo.git"}}}),
        ],
    );
    assert!(rows[0]["repos"][0].get("remote").is_none());
    assert!(rows[0]["repos"][0].get("head").is_none());
}

#[test]
fn goose_steering_keeps_authorship_unknown_and_unlinked_decisions_have_no_subject() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("goose.db");
    let db = Connection::open(&path).unwrap();
    db.execute_batch(
        &fs::read_to_string(root().join("crates/asr-convert/tests/fixtures/sqlite/goose.sql"))
            .unwrap(),
    )
    .unwrap();
    db.execute(
        "UPDATE messages SET metadata_json=?1 WHERE role='user'",
        [json!({"steer":true}).to_string()],
    )
    .unwrap();
    let mut options = Options::new(Agent::Goose, path, temp.path().join("out"));
    options.namespace = Some("example".into());
    convert(&options).unwrap();
    validate(&options.out);
    let rows = read(&options.out);
    assert!(rows
        .iter()
        .any(|r| r.get("author").is_none() && r["origin"] == "queued"));
    let approvals: Vec<_> = rows.iter().filter(|r| r["type"] == "approval").collect();
    assert_eq!(approvals.len(), 1);
    for r in approvals {
        assert!(r.get("subject").is_none());
    }
}

#[test]
fn openhands_event_source_establishes_authorship_and_bare_roles_do_not() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("native.json");
    fs::write(&input, json!({"session_id":"source","id":"prompt","source":"user","action":"message","args":{"content":"A person's input."}}).to_string()).unwrap();
    let out = temp.path().join("out");
    convert(&Options::new(Agent::OpenHands, input, out.clone())).unwrap();
    validate(&out);
    let rows = read(&out);
    assert!(rows
        .iter()
        .any(|r| r["author"] == "human" && r["origin"] == "prompt"));
}

#[test]
fn opencode_error_messages_are_results_without_invented_approvals() {
    for agent in [Agent::OpenCode, Agent::Kilo, Agent::MimoCode] {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("native.db");
        let db = Connection::open(&path).unwrap();
        db.execute_batch(
            &fs::read_to_string(root().join(format!(
                "crates/asr-convert/tests/fixtures/sqlite/{}.sql",
                agent.name()
            )))
            .unwrap(),
        )
        .unwrap();
        let data = json!({"type":"tool","callID":"edit-1","tool":"edit","state":{"status":"error","input":{},"error":{"type":"aborted","message":"The user declined this tool call"}}});
        db.execute(
            "UPDATE part SET data=?1 WHERE id='p3'",
            params![data.to_string()],
        )
        .unwrap();
        let out = temp.path().join("out");
        convert(&Options::new(agent, path, out.clone())).unwrap();
        validate(&out);
        let rows = read(&out);
        assert!(!rows.iter().any(|r| r["type"] == "approval"));
        assert!(rows
            .iter()
            .any(|r| r["type"] == "tool_result" && r["error"]["code"] == "aborted"));
    }
}

#[test]
fn effective_claude_input_drives_edit_evidence_and_keeps_result_metadata() {
    let mut rows = tool(
        "Edit",
        json!({"file_path":"wrong.txt","old_string":"wrong","new_string":"wrong"}),
        json!({"userModified":true,"structuredPatch":[{"lines":["-old","+new"]}]}),
        None,
    );
    rows[1]["updatedInput"] =
        json!({"file_path":"right.txt","old_string":"old\n","new_string":"new\n"});
    let (_, _, rows) = run(Agent::ClaudeCode, &rows);
    assert_eq!(change(&rows)["path"], "/work/app/right.txt");
    assert_eq!(change(&rows)["edits"][0]["newText"], "new\n");
    assert_eq!(
        change(&rows)["_meta"]["com.anthropic.claude-code"]["result"]["userModified"],
        true
    );
    assert_eq!(
        rows.iter().find(|r| r["type"] == "tool_result").unwrap()["input"]["file_path"],
        "right.txt"
    );
}

#[test]
fn invalid_header_failure_names_its_session_and_preserves_neighboring_session() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("native");
    write(
        &input.join("bad.jsonl"),
        &[json!({"type":"session_meta","payload":{"id":"bad-header","timestamp":"invalid-time"}})],
    );
    write(
        &input.join("good.jsonl"),
        &[
            json!({"type":"session_meta","payload":{"id":"good-header","timestamp":"2026-01-01T00:00:00Z"}}),
        ],
    );
    let out = temp.path().join("out");
    let summary = convert(&Options::new(Agent::Codex, input, out.clone())).unwrap();
    assert_eq!(summary.sessions, 1);
    assert_eq!(
        summary.session_diagnostics["codex:bad-header"]["session_header_shape"],
        1
    );
    validate(&out);
    assert_eq!(read(&out)[0]["sessionId"], "good-header");
}

#[test]
fn a_source_staging_failure_does_not_discard_an_independent_source() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("native");
    write(
        &input.join("good.jsonl"),
        &[json!({"type":"session_meta","payload":{"id":"good-source"}})],
    );
    fs::write(input.join("bad.jsonl.zst"), b"invalid compressed input").unwrap();
    let out = temp.path().join("out");
    let summary = convert(&Options::new(Agent::Codex, input, out.clone())).unwrap();
    assert_eq!(summary.sessions, 1);
    assert_eq!(summary.diagnostics["source_staging_failed"], 1);
    assert!(summary
        .session_diagnostics
        .keys()
        .any(|s| s.starts_with("source-")));
    validate(&out);
    assert_eq!(read(&out)[0]["sessionId"], "good-source");
}

#[test]
fn unlinked_openclaw_decision_survives_without_a_subject() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("native.db");
    let db = Connection::open(&path).unwrap();
    db.execute_batch(
        &fs::read_to_string(root().join("crates/asr-convert/tests/fixtures/sqlite/openclaw.sql"))
            .unwrap(),
    )
    .unwrap();
    let out = temp.path().join("out");
    convert(&Options::new(Agent::OpenClaw, path, out.clone())).unwrap();
    validate(&out);
    let rows = read(&out);
    let decisions: Vec<_> = rows.iter().filter(|r| r["type"] == "approval").collect();
    assert_eq!(decisions.len(), 1);
    assert_eq!(decisions[0]["decision"], "approved");
    assert!(decisions[0].get("callId").is_none());
    assert!(decisions[0].get("subject").is_none());
}

#[test]
fn zed_initial_repository_snapshot_keeps_only_recorded_git_facts() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("native.db");
    let db = Connection::open(&path).unwrap();
    db.execute_batch(
        &fs::read_to_string(root().join("crates/asr-convert/tests/fixtures/sqlite/zed.sql"))
            .unwrap(),
    )
    .unwrap();
    let data: Vec<u8> = db
        .query_row("SELECT data FROM threads", [], |r| r.get(0))
        .unwrap();
    let mut thread: Value = serde_json::from_slice(&data).unwrap();
    thread["initial_project_snapshot"] = json!({"worktree_snapshots":[{"worktree_path":"/work/zed","git_state":{"head_sha":"b".repeat(40),"current_branch":"recorded","remote_url":"https://example.com/repo.git"}},{"worktree_path":"/work/plain","git_state":null}]});
    db.execute(
        "UPDATE threads SET data=?1",
        [thread.to_string().as_bytes()],
    )
    .unwrap();
    let out = temp.path().join("out");
    convert(&Options::new(Agent::Zed, path, out.clone())).unwrap();
    validate(&out);
    let rows = read(&out);
    assert!(rows[0].get("cwd").is_none());
    assert_eq!(
        rows[0]["repos"],
        json!([{"path":"/work/zed","head":"b".repeat(40),"branch":"recorded","remote":"https://example.com/repo.git"}])
    );
}

#[test]
fn converter_producers_do_not_claim_full_reasoning_without_native_evidence() {
    fn visit(path: &Path, pattern: &regex::Regex) {
        for entry in fs::read_dir(path).unwrap() {
            let path = entry.unwrap().path();
            if path.is_dir() {
                visit(&path, pattern);
            } else if path.extension().is_some_and(|s| s == "rs") {
                let source = fs::read_to_string(&path).unwrap();
                assert!(
                    !pattern.is_match(&source),
                    "unverified full reasoning in {}",
                    path.display()
                );
            }
        }
    }
    let pattern = regex::Regex::new(r#""visibility"\s*:\s*"full""#).unwrap();
    visit(&root().join("crates/asr-convert/src"), &pattern);
}

#[test]
fn every_converter_has_an_authorship_and_repository_audit_entry() {
    let audit = fs::read_to_string(root().join("crates/asr-convert/MAPPINGS.md")).unwrap();
    for agent in Agent::ALL {
        assert!(
            audit.contains(&format!("| `{}` |", agent.name())),
            "{}",
            agent.name()
        );
    }
}

#[test]
fn codex_patch_evidence_preserves_context_status_and_conservative_framing() {
    for (status, expected) in [
        ("success", "applied"),
        ("failed", "failed"),
        ("cancelled", "unknown"),
    ] {
        let patch = "*** Begin Patch\n*** Update File: file.txt\n@@\n unchanged\n-old\n+new\n*** End Patch\n";
        let (_, _, rows) = run(
            Agent::Codex,
            &[
                json!({"type":"session_meta","payload":{"id":"patch","cwd":"/work/app"}}),
                json!({"type":"response_item","payload":{"type":"custom_tool_call","name":"apply_patch","call_id":"patch","input":patch}}),
                json!({"type":"event_msg","payload":{"type":"patch_apply_end","call_id":"patch","status":status}}),
            ],
        );
        assert_eq!(change(&rows)["status"], expected);
        assert_eq!(
            change(&rows)["edits"],
            json!([{"oldText":"unchanged\nold\n","newText":"unchanged\nnew\n"}])
        );
    }
    for patch in [
        "*** Begin Patch\r\n*** Add File: file.txt\r\n+new\r\n*** End Patch\r\n",
        "*** Begin Patch\n*** Add File: file.txt\n+new\nunknown framing\n*** End Patch",
    ] {
        let (_, _, rows) = run(
            Agent::Codex,
            &[
                json!({"type":"session_meta","payload":{"id":"patch"}}),
                json!({"type":"response_item","payload":{"type":"custom_tool_call","name":"apply_patch","call_id":"patch","input":patch}}),
                json!({"type":"event_msg","payload":{"type":"patch_apply_end","call_id":"patch","success":true}}),
            ],
        );
        assert!(!rows.iter().any(|r| r["type"] == "file_change"));
        assert!(rows[0]["missing"]
            .as_array()
            .unwrap()
            .contains(&json!("file_changes")));
    }
}

#[test]
fn an_empty_claude_git_branch_does_not_establish_a_repository() {
    let (_, _, rows) = run(
        Agent::ClaudeCode,
        &[
            json!({"type":"user","sessionId":"plain-directory","cwd":"/work/plain","gitBranch":"","message":{"content":"Example."}}),
        ],
    );
    assert!(rows[0].get("repos").is_none());
}

#[test]
fn goose_reasoning_without_a_provider_representation_keeps_visibility_unknown() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("native.db");
    let db = Connection::open(&path).unwrap();
    db.execute_batch(
        &fs::read_to_string(root().join("crates/asr-convert/tests/fixtures/sqlite/goose.sql"))
            .unwrap(),
    )
    .unwrap();
    db.execute(
        "UPDATE messages SET content_json=?1 WHERE message_id='assistant'",
        [json!([{"type":"thinking","thinking":"Recorded reasoning."}]).to_string()],
    )
    .unwrap();
    let out = temp.path().join("out");
    let mut options = Options::new(Agent::Goose, path, out.clone());
    options.namespace = Some("synthetic".into());
    convert(&options).unwrap();
    validate(&out);
    let rows = read(&out);
    let part = &rows.iter().find(|r| r["role"] == "assistant").unwrap()["content"][0];
    assert_eq!(part["text"], "Recorded reasoning.");
    assert!(part.get("visibility").is_none());
}
