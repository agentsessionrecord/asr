use asr_convert::{convert, Agent, Options};
use serde_json::{json, Value};
use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
};
fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}
fn records(path: &Path) -> Vec<Value> {
    fs::read_to_string(path)
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect()
}
fn output(dir: &Path) -> PathBuf {
    fs::read_dir(dir)
        .unwrap()
        .map(|e| e.unwrap().path())
        .find(|p| p.extension().is_some_and(|e| e == "jsonl"))
        .unwrap()
}
fn validate(dir: &Path) {
    let result = Command::new("node")
        .arg(repo().join("tools/validator/bin/asr-validate.js"))
        .arg("--summary")
        .arg(dir)
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
}
fn synthetic(agent: Agent, lines: &[Value]) -> (tempfile::TempDir, Vec<Value>) {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("native.jsonl");
    fs::write(
        &input,
        lines.iter().map(|v| format!("{v}\n")).collect::<String>(),
    )
    .unwrap();
    let out = temp.path().join("out");
    convert(&Options::new(agent, input, out.clone())).unwrap();
    validate(&out);
    let data = records(&output(&out));
    (temp, data)
}
#[test]
fn interaction_tools_keep_plan_kinds_questions_and_answers() {
    for (agent, plan, question_tool) in [
        (Agent::ClaudeCode, "TodoWrite", "AskUserQuestion"),
        (Agent::Codex, "update_plan", "request_user_input"),
    ] {
        let question = json!({"questions":[{"id":"color","header":"Color","question":"Which color?\nKeep this spacing:  ","options":[{"label":"Blue","description":"Use blue."},{"label":"Green","description":"Use green."}]}]});
        let answer = "{\"answers\":{\"color\":{\"answers\":[\"Blue\"]}}}\n";
        let steps = if agent == Agent::ClaudeCode {
            json!({"todos":[{"content":"Check colors","status":"in_progress","activeForm":"Checking colors"}]})
        } else {
            json!({"plan":[{"step":"Check colors","status":"in_progress"}]})
        };
        let mut tools = vec![(plan, "think", steps), (question_tool, "other", question)];
        if agent == Agent::ClaudeCode {
            tools.extend([
                ("EnterPlanMode", "switch_mode", json!({})),
                ("ExitPlanMode", "switch_mode", json!({"plan":"Use blue.\n"})),
            ]);
        }
        let mut native = if agent == Agent::ClaudeCode {
            Vec::new()
        } else {
            vec![json!({"type":"session_meta","payload":{"id":"interaction"}})]
        };
        for (index, (name, _, input)) in tools.iter().enumerate() {
            let id = format!("call-{index}");
            let output = if *name == question_tool {
                answer
            } else {
                "Updated."
            };
            if agent == Agent::ClaudeCode {
                native.push(json!({"type":"assistant","sessionId":"interaction","uuid":format!("request-{index}"),"message":{"id":format!("response-{index}"),"model":"example-model","content":[{"type":"tool_use","id":id,"name":name,"input":input}]}}));
                native.push(json!({"type":"user","sessionId":"interaction","uuid":format!("result-{index}"),"message":{"content":[{"type":"tool_result","tool_use_id":id,"is_error":false,"content":output}]}}));
            } else {
                native.push(json!({"type":"response_item","payload":{"type":"function_call","call_id":id,"name":name,"arguments":input.to_string()}}));
                native.push(json!({"type":"response_item","payload":{"type":"function_call_output","call_id":id,"output":output}}));
            }
        }
        let (_, rows) = synthetic(agent, &native);
        let calls: Vec<_> = rows.iter().filter(|r| r["type"] == "tool_call").collect();
        let results: Vec<_> = rows.iter().filter(|r| r["type"] == "tool_result").collect();
        assert_eq!(calls.len(), tools.len());
        assert_eq!(results.len(), tools.len());
        assert!(!rows.iter().any(|r| r["type"] == "approval"));
        for (index, (name, kind, input)) in tools.iter().enumerate() {
            assert_eq!(calls[index]["name"], *name);
            assert_eq!(calls[index]["kind"], *kind);
            assert_eq!(calls[index]["input"], *input);
            assert_eq!(calls[index]["callId"], results[index]["callId"]);
            assert_eq!(calls[index]["requestedBy"], "model");
            let output = if *name == question_tool {
                answer
            } else {
                "Updated."
            };
            assert_eq!(
                results[index]["content"],
                json!([{"type":"text","text":output}])
            );
            assert_eq!(
                results[index]["status"],
                if agent == Agent::ClaudeCode {
                    "completed"
                } else {
                    "unknown"
                }
            );
        }
    }
}
#[test]
fn vendor_content_goldens_keep_native_blocks_and_neighboring_text() {
    for agent in [Agent::Codex, Agent::GeminiCli] {
        let name = agent.name();
        let temp = tempfile::tempdir().unwrap();
        let input = repo().join(format!(
            "crates/asr-convert/tests/fixtures/vendor-content/{name}.jsonl"
        ));
        let out = temp.path().join("out");
        convert(&Options::new(agent, input, out.clone())).unwrap();
        validate(&out);
        let data = records(&output(&out));
        let message = data.iter().find(|r| r["type"] == "message").unwrap();
        let owner = if agent == Agent::Codex {
            "com.openai.codex"
        } else {
            "com.google.gemini-cli"
        };
        assert_eq!(
            message["content"][0],
            json!({"type":format!("{owner}/content"),"_meta":{owner:{"native":{"type":"document","name":"notes.pdf"}}}})
        );
        assert_eq!(
            message["content"][1],
            json!({"type":"text","text":"Read these notes."})
        );
        let golden = repo().join(format!(
            "crates/asr-convert/tests/golden/vendor-content-{name}.jsonl"
        ));
        if std::env::var_os("ASR_UPDATE_VENDOR_GOLDENS").is_some() {
            fs::copy(output(&out), &golden).unwrap();
        }
        assert_eq!(fs::read(output(&out)).unwrap(), fs::read(golden).unwrap());
    }
}
#[test]
fn repository_samples_are_stable_and_valid() {
    for agent in [Agent::ClaudeCode, Agent::Codex] {
        let temp = tempfile::tempdir().unwrap();
        let input = repo().join(format!("samples/{}/native", agent.name()));
        let out = temp.path().join("out");
        let summary = convert(&Options::new(agent, input, out.clone())).unwrap();
        assert_eq!(summary.sessions, 1);
        validate(&out);
        let actual = fs::read(output(&out)).unwrap();
        let golden = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join(format!("tests/golden/{}.jsonl", agent.name()));
        if std::env::var_os("ASR_UPDATE_SAMPLE_GOLDENS").is_some() {
            fs::write(&golden, &actual).unwrap();
        }
        assert_eq!(actual, fs::read(golden).unwrap(), "{} golden", agent.name());
        // Byte stability is independent of which directory contains the source file.
        let copy = temp.path().join("copied.jsonl");
        fs::copy(
            repo().join(format!("samples/{}/native/session.jsonl", agent.name())),
            &copy,
        )
        .unwrap();
        convert(&Options::new(agent, copy, out.clone())).unwrap();
        assert_eq!(actual, fs::read(output(&out)).unwrap());
    }
}
#[test]
fn folded_results_keep_intervening_records_at_completion() {
    let (_, data) = synthetic(
        Agent::Codex,
        &[
            json!({"type":"session_meta","payload":{"id":"folding"}}),
            json!({"type":"response_item","payload":{"type":"function_call","id":"native-call","call_id":"run","name":"exec_command","arguments":"{\"cmd\":\"echo ready\"}"}}),
            json!({"type":"event_msg","timestamp":"2026-10-31T12:00:01Z","payload":{"type":"exec_command_end","call_id":"run","status":"failed","exit_code":1}}),
            json!({"type":"response_item","payload":{"type":"message","id":"notice","role":"user","content":[{"type":"input_text","text":"intervening"}]}}),
            json!({"type":"response_item","timestamp":"2026-10-31T12:00:03Z","payload":{"type":"function_call_output","call_id":"run","output":"model-facing output"}}),
        ],
    );
    let result = data
        .iter()
        .position(|v| v["type"] == "tool_result")
        .unwrap();
    let notice = data.iter().position(|v| v["id"] == "notice").unwrap();
    assert!(notice < result);
    assert_eq!(
        data.iter().filter(|v| v["type"] == "tool_result").count(),
        1
    );
    assert_eq!(data[result]["status"], "failed");
    assert_eq!(data[result]["ts"], "2026-10-31T12:00:03Z");
    assert_eq!(data[result]["content"][0]["text"], "model-facing output");
}
#[test]
fn missing_model_does_not_drop_recorded_inference_and_unsafe_ids_are_strings() {
    let (_, data) = synthetic(
        Agent::Codex,
        &[
            json!({"type":"session_meta","payload":{"id":"no-model"}}),
            json!({"type":"token_usage_record","payload":{"response_id":"response-native","usage":{"input_tokens":0,"output_tokens":0}}}),
            json!({"type":"response_item","payload":{"type":"function_call","call_id":"run","name":"native","arguments":"{\"id\":9007199254740993123456789}"}}),
        ],
    );
    let inference = data.iter().find(|v| v["type"] == "inference").unwrap();
    assert!(inference.get("model").is_none());
    assert_eq!(inference["usage"]["inputTokens"], 0);
    assert!(data[0]["missing"]
        .as_array()
        .unwrap()
        .contains(&json!("model")));
    let call = data.iter().find(|v| v["type"] == "tool_call").unwrap();
    assert_eq!(call["input"]["id"], "9007199254740993123456789");
}
#[test]
fn repeated_claude_snapshots_use_last_and_approvals_have_no_borrowed_time() {
    let (_, data) = synthetic(
        Agent::ClaudeCode,
        &[
            json!({"type":"user","sessionId":"snapshots","uuid":"prompt","message":{"content":"first"}}),
            json!({"type":"user","sessionId":"snapshots","uuid":"prompt","message":{"content":"last"}}),
            json!({"type":"assistant","sessionId":"snapshots","uuid":"call-row","message":{"id":"response","content":[{"type":"tool_use","id":"tool","name":"Read","input":{"file_path":"a"}}],"model":"model"}}),
            json!({"type":"user","sessionId":"snapshots","uuid":"result-row","timestamp":"2026-10-31T12:00:03Z","permissionDecision":{"decision":"accept","source":"config"},"message":{"content":[{"type":"tool_result","tool_use_id":"tool","content":"done","is_error":false}]}}),
        ],
    );
    assert_eq!(data.iter().filter(|v| v["id"] == "prompt").count(), 1);
    assert_eq!(
        data.iter().find(|v| v["id"] == "prompt").unwrap()["content"][0]["text"],
        "last"
    );
    let index = data.iter().position(|v| v["type"] == "approval").unwrap();
    assert!(data[index].get("ts").is_none());
    assert_eq!(data[index]["by"], "policy");
    assert_eq!(data[index + 1]["type"], "tool_result");
}

#[test]
fn approval_snapshots_follow_repeated_results_without_prefix_collisions() {
    let (_, data) = synthetic(
        Agent::ClaudeCode,
        &[
            json!({"type":"user","sessionId":"approval-folds","message":{"content":"prompt"}}),
            json!({"type":"assistant","sessionId":"approval-folds","uuid":"calls","message":{"id":"response","model":"model","content":[{"type":"tool_use","id":"run","name":"Read","input":{}},{"type":"tool_use","id":"run;other","name":"Read","input":{}}]}}),
            json!({"type":"user","sessionId":"approval-folds","uuid":"first","permissionDecision":{"decision":"accept","source":"config"},"message":{"content":[{"type":"tool_result","tool_use_id":"run","content":"first","is_error":false}]}}),
            json!({"type":"user","sessionId":"approval-folds","uuid":"other","permissionDecision":{"decision":"accept","source":"user"},"message":{"content":[{"type":"tool_result","tool_use_id":"run;other","content":"other","is_error":false}]}}),
            json!({"type":"user","sessionId":"approval-folds","uuid":"notice","message":{"content":"intervening"}}),
            json!({"type":"user","sessionId":"approval-folds","uuid":"last","timestamp":"2026-10-31T12:00:03Z","permissionDecision":{"decision":"accept","source":"user"},"message":{"content":[{"type":"tool_result","tool_use_id":"run","content":"last","is_error":false}]}}),
        ],
    );
    let last = data
        .iter()
        .position(|v| v["type"] == "tool_result" && v["callId"] == "run")
        .unwrap();
    assert_eq!(data[last]["content"][0]["text"], "last");
    assert_eq!(data[last]["ts"], "2026-10-31T12:00:03Z");
    for record in &data[last - 2..last] {
        assert_eq!(record["type"], "approval");
        assert_eq!(record["callId"], "run");
        assert!(record.get("ts").is_none());
    }
    let other = data
        .iter()
        .position(|v| v["type"] == "tool_result" && v["callId"] == "run;other")
        .unwrap();
    let notice = data.iter().position(|v| v["id"] == "notice").unwrap();
    assert!(other < notice && notice < last - 2);
    assert_eq!(data[other - 1]["callId"], "run;other");
}
#[test]
fn malformed_source_recovers_and_incomplete_tail_is_deferred() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("native.jsonl");
    fs::write(&input,"{\"type\":\"session_meta\",\"payload\":{\"id\":\"recovery\"}}\n{bad}\n{\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"id\":\"good\",\"role\":\"user\",\"content\":[]}}\n{\"tail\":").unwrap();
    let out = temp.path().join("out");
    let summary = convert(&Options::new(Agent::Codex, input, out.clone())).unwrap();
    assert_eq!(summary.diagnostics["unparseable_source_line"], 1);
    assert_eq!(summary.diagnostics["incomplete_source_tail"], 1);
    let data = records(&output(&out));
    assert!(data.iter().any(|v| v["type"] == "gap"));
    assert!(data.iter().any(|v| v["id"] == "good"));
    validate(&out);
}
#[test]
fn explicit_credentials_and_secret_answers_are_removed_everywhere() {
    let private = concat!("synthetic-", "credential-", "value");
    let (_, data) = synthetic(
        Agent::ClaudeCode,
        &[
            json!({"type":"user","sessionId":"privacy","message":{"content":format!("earlier {private}")}}),
            json!({"type":"native-question","sessionId":"privacy","questions":[{"id":"q","secret":true}]}),
            json!({"type":"native-answer","sessionId":"privacy","answers":{"q":private}}),
            json!({"type":"native-auth","sessionId":"privacy","api_key":private}),
            json!({"type":"user","sessionId":"privacy","message":{"content":"Follow basic instructions. synthetic-session-echo synthetic-client-echo"}}),
            json!({"type":"native-auth","sessionId":"privacy","sessionToken":"synthetic-session-echo","clientSecret":"synthetic-client-echo"}),
        ],
    );
    assert!(!serde_json::to_string(&data).unwrap().contains(private));
    let raw = serde_json::to_string(&data).unwrap();
    assert!(!raw.contains("synthetic-session-echo"));
    assert!(!raw.contains("synthetic-client-echo"));
    assert!(raw.contains("Follow basic instructions."));
    assert!(data[0]["missing"]
        .as_array()
        .unwrap()
        .contains(&json!("redacted_content")));
}

#[test]
fn native_null_call_settings_and_malformed_media_stay_valid() {
    let (_, data) = synthetic(
        Agent::ClaudeCode,
        &[
            json!({"type":"user","sessionId":"media","uuid":"prompt","message":{"content":[{"type":"image","source":{"type":"base64","media_type":"image/png","data":"shortened [native]"}}]}}),
            json!({"type":"assistant","sessionId":"media","uuid":"response-row","message":{"id":"response","model":"model","stop_reason":"end_turn","usage":{"input_tokens":0,"output_tokens":0,"service_tier":null},"content":[{"type":"text","text":"done"}]}}),
        ],
    );
    let media = data.iter().find(|v| v["id"] == "prompt").unwrap();
    assert!(media["content"][0].get("data").is_none());
    assert_eq!(media["truncated"], true);
    let inference = data.iter().find(|v| v["type"] == "inference").unwrap();
    assert!(inference["settings"].get("serviceTier").is_none());
}

#[test]
fn sample_actions_approvals_usage_and_completion_times_match_committed_asr() {
    for agent in [Agent::ClaudeCode, Agent::Codex] {
        let old = records(&repo().join(format!("samples/{}/asr/session.jsonl", agent.name())));
        let new = records(
            &Path::new(env!("CARGO_MANIFEST_DIR"))
                .join(format!("tests/golden/{}.jsonl", agent.name())),
        );
        for expected in old.iter().filter(|v| {
            matches!(
                v["type"].as_str(),
                Some("tool_call" | "tool_result" | "approval" | "file_change" | "inference")
            )
        }) {
            let matched: Vec<_> = new
                .iter()
                .filter(|v| {
                    v["type"] == expected["type"]
                        && if expected.get("callId").is_some() {
                            v["callId"] == expected["callId"]
                        } else {
                            v["id"] == expected["id"]
                        }
                })
                .collect();
            assert_eq!(matched.len(), 1);
            let clean = |value: &Value| {
                let mut value = value.clone();
                for key in ["_meta", "id", "truncated", "locations"] {
                    value.as_object_mut().unwrap().remove(key);
                }
                value
            };
            assert_eq!(
                clean(matched[0]),
                clean(expected),
                "{} {}",
                agent.name(),
                expected["type"]
            );
        }
    }
}

#[test]
fn recorded_effective_null_input_survives_and_synthetic_messages_are_not_calls() {
    let (_, data) = synthetic(
        Agent::ClaudeCode,
        &[
            json!({"type":"user","sessionId":"effective","message":{"content":"prompt"}}),
            json!({"type":"assistant","sessionId":"effective","uuid":"synthetic","message":{"id":"placeholder","model":"<synthetic>","content":[{"type":"text","text":"retry"}]}}),
            json!({"type":"assistant","sessionId":"effective","uuid":"call","message":{"id":"response","model":"model","content":[{"type":"tool_use","id":"run","name":"Read","input":{"path":"requested"}}]}}),
            json!({"type":"user","sessionId":"effective","uuid":"result","updatedInput":null,"message":{"content":[{"type":"tool_result","tool_use_id":"run","is_error":false,"content":"done"}]}}),
        ],
    );
    assert_eq!(data.iter().filter(|v| v["type"] == "inference").count(), 1);
    let result = data.iter().find(|v| v["type"] == "tool_result").unwrap();
    assert!(result.get("input").is_some_and(Value::is_null));
}

#[test]
fn input_is_unchanged_when_output_is_inside_it() {
    let temp = tempfile::tempdir().unwrap();
    let out = temp.path().join("nested/out");
    assert!(convert(&Options::new(
        Agent::Codex,
        temp.path().to_owned(),
        out.clone()
    ))
    .is_err());
    assert!(!out.exists());
}

#[test]
fn inference_links_follow_remapped_native_ids() {
    for response in ["shared", "header", "unsafe\u{85}"] {
        let (_, data) = synthetic(
            Agent::ClaudeCode,
            &[
                json!({"type":"user","sessionId":"collision","uuid":response,"message":{"content":"prompt"}}),
                json!({"type":"assistant","sessionId":"collision","uuid":"response-row","message":{"id":response,"model":"model","content":[{"type":"text","text":"reply"},{"type":"tool_use","id":"run","name":"Read","input":{}}]}}),
            ],
        );
        let inference = data.iter().find(|v| v["type"] == "inference").unwrap();
        let links: Vec<_> = data.iter().filter_map(|v| v.get("inferenceId")).collect();
        assert_eq!(links.len(), 2);
        assert!(links.iter().all(|id| **id == inference["id"]));
        assert_ne!(inference["id"], response);
    }
}

#[test]
fn codex_thread_ids_do_not_merge_spawn_trees_or_select_ancestor_metadata() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("input");
    fs::create_dir(&input).unwrap();
    let root = "00000000-0000-4000-8000-000000000000";
    let child = "00000000-0000-4000-8000-000000000001";
    let parent = json!({"type":"session_meta","payload":{"id":root,"session_id":root}});
    let own = json!({"type":"session_meta","payload":{"id":child,"session_id":root,"source":{"subagent":{"thread_spawn":{"parent_thread_id":root}}}}});
    fs::write(input.join("root.jsonl"), format!("{parent}\n")).unwrap();
    fs::write(
        input.join(format!("rollout-2026-10-31T12-00-00-{child}.jsonl")),
        format!("{parent}\n{own}\n{parent}\n"),
    )
    .unwrap();
    fs::write(input.join("ambiguous.jsonl"), format!("{parent}\n{own}\n")).unwrap();
    let out = temp.path().join("out");
    let summary = convert(&Options::new(Agent::Codex, input, out.clone())).unwrap();
    assert_eq!(summary.sessions, 2);
    assert_eq!(summary.diagnostics["unidentified_source"], 1);
    validate(&out);
    let headers: Vec<_> = fs::read_dir(out)
        .unwrap()
        .map(|p| records(&p.unwrap().path())[0].clone())
        .collect();
    assert!(headers.iter().any(|v| v["sessionId"] == root));
    let child_header = headers.iter().find(|v| v["sessionId"] == child).unwrap();
    assert_eq!(child_header["parent"]["session"], format!("codex:{root}"));
}

#[test]
fn compressed_aliases_are_read_once_and_outputs_are_private() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("input");
    fs::create_dir(&input).unwrap();
    let bytes = b"{\"type\":\"session_meta\",\"payload\":{\"id\":\"compressed\"}}\n";
    fs::write(input.join("session.jsonl"), bytes).unwrap();
    fs::write(
        input.join("session.jsonl.zst"),
        zstd::encode_all(&bytes[..], 1).unwrap(),
    )
    .unwrap();
    let out = temp.path().join("output");
    let summary = convert(&Options::new(Agent::Codex, input, out.clone())).unwrap();
    assert_eq!(summary.files, 1);
    assert_eq!(summary.sessions, 1);
    validate(&out);
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(
            fs::metadata(&out).unwrap().permissions().mode() & 0o777,
            0o700
        );
        assert_eq!(
            fs::metadata(output(&out)).unwrap().permissions().mode() & 0o777,
            0o600
        );
    }
}
