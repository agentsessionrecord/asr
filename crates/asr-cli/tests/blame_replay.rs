//! Native-shaped sessions must reproduce each credited line, including mixed work.
use serde_json::{json, Value};
use std::{
    cell::Cell,
    fs,
    path::{Path, PathBuf},
    process::Command,
};

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}
fn run(program: &str, args: &[&str], cwd: &Path) -> String {
    run_at(program, args, cwd, 1767225600)
}
fn run_at(program: &str, args: &[&str], cwd: &Path, at: i64) -> String {
    let out = Command::new(program)
        .args(args)
        .current_dir(cwd)
        .env("GIT_AUTHOR_DATE", format!("@{at} +0000"))
        .env("GIT_COMMITTER_DATE", format!("@{at} +0000"))
        .env("GIT_CONFIG_NOSYSTEM", "1")
        .env("GIT_CONFIG_GLOBAL", "/dev/null")
        .env("GIT_AUTHOR_NAME", "Synthetic")
        .env("GIT_COMMITTER_NAME", "Synthetic")
        .env("GIT_AUTHOR_EMAIL", "test@example.invalid")
        .env("GIT_COMMITTER_EMAIL", "test@example.invalid")
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8(out.stdout).unwrap()
}
struct Case {
    temp: tempfile::TempDir,
    native: Vec<Value>,
    agent: &'static str,
    clock: Cell<i64>,
    contents: String,
}
impl Case {
    fn new(agent: &'static str, baseline: &str) -> Self {
        let temp = tempfile::tempdir().unwrap();
        let p = temp.path();
        fs::create_dir(p.join("repo")).unwrap();
        let mut c = Self {
            temp,
            native: vec![],
            agent,
            clock: Cell::new(1767225600),
            contents: String::new(),
        };
        run("git", &["init", "-q"], &c.repo());
        c.commit(baseline);
        let cwd = c.repo();
        c.native = if agent == "claude-code" {
            vec![
                json!({"type":"user","uuid":"prompt","sessionId":"synthetic-replay","cwd":cwd,"version":"2.1.305","promptId":"turn-1","origin":{"kind":"human"},"message":{"role":"user","content":"Update the calculation."}}),
            ]
        } else {
            vec![
                json!({"type":"session_meta","payload":{"id":"synthetic-replay","cwd":cwd,"cli_version":"0.163.0"}}),
                json!({"type":"turn_context","payload":{"turn_id":"turn-1","model":"example-model"}}),
                json!({"type":"response_item","payload":{"type":"message","id":"prompt","role":"user","content":[{"type":"input_text","text":"Update the calculation."}]}}),
            ]
        };
        c
    }
    fn repo(&self) -> PathBuf {
        self.temp.path().join("repo")
    }
    fn tick(&self) -> i64 {
        let at = self.clock.get() + 60;
        self.clock.set(at);
        at
    }
    fn commit(&mut self, contents: &str) {
        self.contents = contents.to_owned();
        let at = self.tick();
        fs::write(self.repo().join("file.py"), contents).unwrap();
        run(
            "git",
            &["-c", "core.hooksPath=/dev/null", "add", "file.py"],
            &self.repo(),
        );
        run_at(
            "git",
            &[
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-qm",
                "Synthetic change",
            ],
            &self.repo(),
            at,
        );
    }
    fn edit(&mut self, id: &str, old: &str, new: &str) {
        self.edit_all(id, old, new, false);
    }
    fn edit_all(&mut self, id: &str, old: &str, new: &str, all: bool) {
        let after = if all {
            self.contents.replace(old, new)
        } else {
            self.contents.replacen(old, new, 1)
        };
        let patch = similar::TextDiff::from_lines(&self.contents, &after)
            .unified_diff()
            .context_radius(3)
            .to_string();
        let header = regex::Regex::new(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@").unwrap();
        let mut hunks: Vec<Value> = Vec::new();
        for line in patch.lines() {
            if let Some(m) = header.captures(line) {
                let number =
                    |i: usize| m.get(i).map_or(1, |v| v.as_str().parse::<usize>().unwrap());
                hunks.push(json!({"oldStart":number(1),"oldLines":number(2),"newStart":number(3),"newLines":number(4),"lines":[]}));
            } else if let Some(hunk) = hunks.last_mut() {
                hunk["lines"].as_array_mut().unwrap().push(json!(line));
            }
        }
        self.claude(id, "Edit", json!({"file_path":self.repo().join("file.py"),"old_string":old,"new_string":new,"replace_all":all}),
            json!({"filePath":self.repo().join("file.py"),"oldString":old,"newString":new,"originalFile":null,"structuredPatch":hunks,"replaceAll":all,"userModified":false,"contentNotInModelContext":false}));
        self.contents = after;
    }
    fn write(&mut self, contents: &str) {
        self.contents = contents.to_owned();
        self.claude("write", "Write", json!({"file_path":self.repo().join("file.py"),"content":contents}),
            json!({"type":"update","filePath":self.repo().join("file.py"),"content":contents,"originalFile":null,"structuredPatch":[]}));
    }
    fn claude(&mut self, id: &str, name: &str, input: Value, output: Value) {
        let ts = chrono::DateTime::from_timestamp(self.tick(), 0)
            .unwrap()
            .to_rfc3339();
        let sid = self
            .native
            .last()
            .and_then(|r| r["sessionId"].as_str())
            .unwrap_or("synthetic-replay")
            .to_owned();
        self.native.extend([
            json!({"timestamp":ts,"type":"assistant","uuid":format!("{id}-request"),"parentUuid":"prompt","promptId":"turn-1","sessionId":sid,"message":{"id":format!("{id}-response"),"role":"assistant","model":"example-model","content":[{"type":"tool_use","id":id,"name":name,"input":input}],"usage":{"input_tokens":10,"output_tokens":5}}}),
            json!({"timestamp":ts,"type":"user","uuid":format!("{id}-result"),"parentUuid":format!("{id}-request"),"promptId":"turn-1","sourceToolAssistantUUID":format!("{id}-request"),"sessionId":sid,"toolUseResult":output,"message":{"role":"user","content":[{"type":"tool_result","tool_use_id":id,"content":"Applied."}]}}),
        ]);
    }
    fn patch(&mut self, id: &str, diff: &str) {
        let ts = chrono::DateTime::from_timestamp(self.tick(), 0)
            .unwrap()
            .to_rfc3339();
        self.native.push(json!({"timestamp":ts,"type":"event_msg","payload":{"type":"item_completed","turn_id":"turn-1","item":{"type":"FileChange","id":id,"status":"completed","changes":{"file.py":{"type":"update","unified_diff":diff}}}}}));
    }
    fn convert(&self) -> PathBuf {
        let source = self.temp.path().join("native");
        fs::create_dir(&source).unwrap();
        let mut sessions = std::collections::BTreeMap::<String, String>::new();
        for r in &self.native {
            let sid = r["sessionId"].as_str().unwrap_or("synthetic");
            sessions
                .entry(sid.to_owned())
                .or_default()
                .push_str(&format!("{r}\n"));
        }
        for (i, records) in sessions.values().enumerate() {
            fs::write(source.join(format!("{i}.jsonl")), records).unwrap();
        }
        let out = self.temp.path().join("converted");
        let summary: Value = serde_json::from_str(&run(
            env!("CARGO_BIN_EXE_asr"),
            &[
                "convert",
                "--agent",
                self.agent,
                source.to_str().unwrap(),
                "--out",
                out.to_str().unwrap(),
            ],
            &root(),
        ))
        .unwrap();
        assert_eq!(summary["sessions"], sessions.len());
        let validation: Value = serde_json::from_str(&run(
            "node",
            &[
                root()
                    .join("tools/validator/bin/asr-validate.js")
                    .to_str()
                    .unwrap(),
                "--json",
                "--summary",
                out.to_str().unwrap(),
            ],
            &root(),
        ))
        .unwrap();
        assert_eq!(validation["errors"], 0);
        println!(
            "{}",
            json!({"agent":self.agent,"validationErrors":validation["errors"],"validationWarnings":validation["warnings"],"validationCodes":validation["counts"]})
        );
        out
    }
    fn check(&self, out: &Path, expected: &[Option<&str>]) {
        self.check_file(out, "file.py", expected);
    }
    fn check_file(&self, out: &Path, file: &str, expected: &[Option<&str>]) {
        let mut correct = 0;
        let mut unknown = 0;
        for (i, call) in expected.iter().enumerate() {
            let result: Value = serde_json::from_str(&run(
                env!("CARGO_BIN_EXE_asr"),
                &[
                    "blame",
                    file,
                    "--line",
                    &(i + 1).to_string(),
                    "--repo",
                    self.repo().to_str().unwrap(),
                    "--sessions",
                    out.to_str().unwrap(),
                ],
                &root(),
            ))
            .unwrap();
            if call.is_some() && result["editStatus"] == "unknown" {
                unknown += 1;
                continue;
            }
            if let Some(call) = call {
                assert_eq!(result["editStatus"], "matched", "line {}: {result}", i + 1);
                assert!(
                    result["editedBy"][0]["call"]
                        .as_str()
                        .unwrap()
                        .ends_with(&format!("#{call}")),
                    "{result}"
                );
                if self.agent == "claude-code" {
                    assert_eq!(result["editedBy"][0]["model"]["value"], "example-model");
                } else {
                    // FileChange has no native inference link. Nearby turn settings
                    // do not establish the model that caused the edit.
                    assert!(result["editedBy"][0]["model"].is_null());
                }
                correct += 1;
            } else {
                assert_eq!(result["editStatus"], "unknown", "line {}: {result}", i + 1);
                unknown += 1;
            }
        }
        println!(
            "{}",
            json!({"agent":self.agent,"correct":correct,"unknown":unknown,"wrong":0})
        );
    }
}

#[test]
fn person_changes_after_claude_are_unknown_in_later_and_mixed_commits() {
    for recorded in [false, true] {
        for separate in [true, false] {
            for (before, old, new, agent, human) in [
                (
                    "def add(a, b, c):\n    return a + b\n",
                    "return a + b",
                    "return a + b + c",
                    "def add(a, b, c):\n    return a + b + c\n",
                    "def add(a, b, c):\n    return a + b + c  # person note\n",
                ),
                (
                    "debug = False\n",
                    "False",
                    "True",
                    "debug = True\n",
                    "verbose = True\n",
                ),
            ] {
                let mut c = Case::new("claude-code", before);
                c.edit("agent", old, new);
                if recorded {
                    c.native.last_mut().unwrap()["toolUseResult"]["originalFile"] = json!(before);
                }
                let out = c.convert();
                if separate {
                    c.commit(agent);
                    c.check(
                        &out,
                        &if agent.starts_with("def") {
                            vec![None, Some("agent")]
                        } else {
                            vec![Some("agent")]
                        },
                    );
                }
                c.commit(human);
                c.check(&out, &vec![None; human.lines().count()]);
            }
        }
    }
}

#[test]
fn claude_recovers_surviving_multiline_edits_and_preserves_person_lines() {
    let mut c = Case::new("claude-code", "first = 0\nsecond = 0\nthird = 0\n");
    c.edit("first", "first = 0\nsecond = 0", "first = 1\nsecond = 1");
    c.edit("second", "second = 1", "second = 2");
    let out = c.convert();
    c.commit("first = 1\nsecond = 2\nthird = 3  # person\n");
    c.check(&out, &[Some("first"), Some("second"), None]);
}

#[test]
fn claude_after_person_uses_the_persons_commit_as_baseline() {
    let mut c = Case::new("claude-code", "debug = False\n");
    c.commit("verbose = False\n");
    c.edit("agent", "False", "True");
    let out = c.convert();
    c.commit("verbose = True\n");
    c.check(&out, &[Some("agent")]);
}

#[test]
fn codex_replays_neighboring_patches_and_rejects_person_changes() {
    let mut c = Case::new("codex", "def add(a, b):\n    return a + b\n");
    c.patch(
        "doc",
        "@@ -1,2 +1,3 @@\n def add(a, b):\n+    \"\"\"Add the inputs.\"\"\"\n     return a + b\n",
    );
    c.patch("body", "@@ -1,3 +1,3 @@\n def add(a, b):\n     \"\"\"Add the inputs.\"\"\"\n-    return a + b\n+    return sum((a, b))\n");
    let out = c.convert();
    c.commit("def add(a, b):\n    \"\"\"Add the inputs.\"\"\"\n    return sum((a, b))\n");
    c.check(&out, &[None, Some("doc"), Some("body")]);
    c.commit(
        "def add(a, b):\n    \"\"\"Add the inputs.\"\"\"  # person\n    return sum((a, b)) + 1\n",
    );
    c.check(&out, &[None, None, None]);
}

#[test]
fn formatter_between_write_and_edit_retries_parent_without_crediting_affixes() {
    let mut c = Case::new("claude-code", "values = [1, 2]\nkeep = 0\n");
    c.write("values=[1,2]\nkeep=0\n");
    c.contents = "values = [1, 2]\nkeep = 0\n".into();
    c.edit("formatted", "values = [1, 2]", "values = [1, 2, 3]");
    let out = c.convert();
    c.commit("values = [1, 2, 3]\nkeep = 0\n");
    c.check(&out, &[Some("formatted"), None]);
    c.commit("values = [1, 2, 3]  # person\nkeep = 0\n");
    c.check(&out, &[None, None]);
}

#[test]
fn stale_write_with_unverifiable_native_context_stays_unknown() {
    let mut c = Case::new("claude-code", "baseline = 0\n");
    c.write("values=[1,2]\n");
    c.contents = "values = [1, 2]\nkeep = 0\n".into();
    c.edit("formatted", "values = [1, 2]", "values = [1, 2, 3]");
    let out = c.convert();
    c.commit("values = [1, 2, 3]\n");
    c.check(&out, &[None]);
    c.commit("values = [1, 2, 3]  # person\n");
    c.check(&out, &[None]);
}

#[test]
fn unobserved_person_change_before_a_partial_edit_in_one_commit_stays_unknown() {
    let mut c = Case::new("claude-code", "debug = False\n");
    c.edit("agent", "False", "True");
    let out = c.convert();
    // The parent replay produces debug = True. The record cannot prove that
    // the person changed the prefix before the agent ran.
    c.commit("verbose = True\n");
    c.check(&out, &[None]);
}

#[test]
fn stale_replay_rejects_text_already_in_the_parent() {
    let mut c = Case::new("claude-code", "values = [1, 2, 3]\nkeep = 0\n");
    c.write("values=[1,2]\nkeep=0\n");
    c.contents = "values = [1, 2]\nkeep = 0\n".into();
    c.edit("formatted", "values = [1, 2]", "values = [1, 2, 3]");
    let out = c.convert();
    c.commit("values = [1, 2, 3]  # person\nkeep = 0\n");
    c.check(&out, &[None, None]);
}

#[test]
fn converted_claude_edit_masks_remove_repeated_full_file_metadata() {
    let before = "def add(a, b):\n    return a + b\n";
    let old = "def add(a, b):\n    return a + b";
    let new = "def add(a, b, c):\n    return a + b + c";
    let mut c = Case::new("claude-code", before);
    c.edit("agent", old, new);
    let result = c.native.last_mut().unwrap();
    result["toolUseResult"]["originalFile"] = json!(before);
    result["toolUseResult"]["content"] = json!(format!("{new}\n"));
    result["toolUseResult"]["structuredPatch"] = json!([{"lines":["-def add(a, b):","-    return a + b","+def add(a, b, c):","+    return a + b + c"]}]);
    let converted = c.convert();
    let source = fs::read_dir(&converted)
        .unwrap()
        .next()
        .unwrap()
        .unwrap()
        .path();
    let out = c.temp.path().join("masked.jsonl");
    let report: Value = serde_json::from_str(&run(
        env!("CARGO_BIN_EXE_asr"),
        &[
            "redact",
            source.to_str().unwrap(),
            "--out",
            out.to_str().unwrap(),
            "--mask",
            "/edits",
        ],
        &root(),
    ))
    .unwrap();
    assert_eq!(report["validated"], true);
    let text = fs::read_to_string(out).unwrap();
    for line in old.lines().chain(new.lines()) {
        assert!(!text.contains(line));
    }
}

// Recheck 3: every C1 shape must reject the later person's line, with and
// without full contents. Keeping the old context removes the timing ambiguity.
#[test]
fn c1_old_flag_rename_and_replace_all_cannot_replay_on_later_person_commits() {
    for recorded in [false, true] {
        for all in [false, true] {
            let before = "def load(uid):\n    return get_user(uid)\n";
            let agent = "def load(uid):\n    return fetch_user(uid)\n";
            let mut c = Case::new("claude-code", before);
            c.edit_all("rename", "get_user", "fetch_user", all);
            if recorded {
                c.native.last_mut().unwrap()["toolUseResult"]["originalFile"] = json!(before);
            }
            c.commit(agent);
            let pasted = "def load(uid):\n    return fetch_user(uid)\nrecord = get_user(uid)\n";
            c.commit(pasted);
            c.clock.set(c.clock.get() + 21 * 86400);
            c.commit("def load(uid):\n    return fetch_user(uid)\nrecord = fetch_user(uid)\n");
            let out = c.convert();
            c.check(&out, &[None, Some("rename"), None]);
        }
        let before = "debug = False\ncache = True\n";
        let mut c = Case::new("claude-code", before);
        c.edit("flag", "False", "True");
        if recorded {
            c.native.last_mut().unwrap()["toolUseResult"]["originalFile"] = json!(before);
        }
        c.commit("debug = True\ncache = True\n");
        c.commit("debug = True\ncache = False\n");
        c.commit("debug = True\ncache = True\n");
        let out = c.convert();
        c.check(&out, &[Some("flag"), None]);
    }
}

#[test]
fn c1_same_window_still_requires_claude_hunk_context_and_position() {
    // Timing alone cannot disambiguate two edits before the same commit.
    for all in [false, true] {
        let mut c = Case::new("claude-code", "debug = False\ncache = False\n");
        c.contents = "debug = False\ncache = True\n".into();
        c.edit_all("flag", "False", "True", all);
        c.commit("debug = False\ncache = True\n");
        let out = c.convert();
        c.check(&out, &[None, None]);
    }
    // Correct text at the wrong recorded line is not the recorded edit.
    let mut c = Case::new("claude-code", "debug = False\n");
    c.edit("flag", "False", "True");
    c.native.last_mut().unwrap()["toolUseResult"]["structuredPatch"][0]["oldStart"] = json!(2);
    c.commit("debug = True\n");
    let out = c.convert();
    c.check(&out, &[None]);
}

#[test]
fn c1_deleted_claude_writes_and_codex_adds_do_not_credit_recreated_files() {
    for agent in ["claude-code", "codex"] {
        let mut c = Case::new(agent, "baseline\n");
        run("git", &["rm", "file.py"], &c.repo());
        run_at(
            "git",
            &[
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-qm",
                "Delete baseline",
            ],
            &c.repo(),
            c.tick(),
        );
        let written = "#!/usr/bin/env python3\nimport json\n\nprint('agent')\n";
        if agent == "claude-code" {
            c.write(written);
            c.native.last_mut().unwrap()["toolUseResult"]["type"] = json!("create");
        } else {
            let ts = chrono::DateTime::from_timestamp(c.tick(), 0)
                .unwrap()
                .to_rfc3339();
            c.native.push(json!({"timestamp":ts,"type":"event_msg","payload":{"type":"item_completed","item":{"type":"FileChange","id":"add","status":"completed","changes":{"file.py":{"type":"add","content":written}}}}}));
        }
        c.commit(written);
        let out = c.convert();
        c.check(
            &out,
            &[
                Some(if agent == "claude-code" {
                    "write"
                } else {
                    "add"
                }),
                Some(if agent == "claude-code" {
                    "write"
                } else {
                    "add"
                }),
                Some(if agent == "claude-code" {
                    "write"
                } else {
                    "add"
                }),
                Some(if agent == "claude-code" {
                    "write"
                } else {
                    "add"
                }),
            ],
        );
        run("git", &["rm", "file.py"], &c.repo());
        run_at(
            "git",
            &[
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-qm",
                "Delete agent file",
            ],
            &c.repo(),
            c.tick(),
        );
        c.commit("#!/usr/bin/env python3\nimport json\n\nprint('person')\n");
        c.check(&out, &[None, None, None, None]);
    }
}

#[test]
fn c1_retyped_reverts_are_unknown_and_revert_of_revert_is_conservative() {
    for native_revert in [false, true] {
        let mut c = Case::new("claude-code", "debug = False\n");
        c.edit("flag", "False", "True");
        c.commit("debug = True\n");
        let agent_commit = run("git", &["rev-parse", "HEAD"], &c.repo());
        run_at(
            "git",
            &[
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "commit.gpgsign=false",
                "revert",
                "--no-edit",
                agent_commit.trim(),
            ],
            &c.repo(),
            c.tick(),
        );
        if native_revert {
            let revert = run("git", &["rev-parse", "HEAD"], &c.repo());
            run_at(
                "git",
                &[
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "commit.gpgsign=false",
                    "revert",
                    "--no-edit",
                    revert.trim(),
                ],
                &c.repo(),
                c.tick(),
            );
        } else {
            c.commit("debug = True\n");
        }
        let out = c.convert();
        c.check(&out, &[None]);
    }
}

#[test]
fn c2_future_edits_cannot_credit_existing_lines_with_any_recorded_baseline() {
    for contents in [false, true] {
        for write in [false, true] {
            for later_commit in [false, true] {
                let mut c = Case::new("claude-code", "retries = 3\nother = 0\n");
                let initial = c.contents.clone();
                if write {
                    c.write(&initial);
                }
                c.edit("increase", "retries = 3", "retries = 5");
                if contents {
                    c.native.last_mut().unwrap()["toolUseResult"]["originalFile"] = json!(initial);
                }
                c.edit("restore", "retries = 5", "retries = 3");
                if contents {
                    c.native.last_mut().unwrap()["toolUseResult"]["originalFile"] =
                        json!("retries = 5\nother = 0\n");
                }
                if later_commit {
                    c.edit("real", "other = 0", "other = 1");
                    c.commit("retries = 3\nother = 1\n");
                }
                let out = c.convert();
                c.check(
                    &out,
                    &[None, if later_commit { Some("real") } else { None }],
                );
            }
        }
    }
}

#[test]
fn c3_undone_edits_are_not_present_in_the_sessions_net_result() {
    for recorded in [false, true] {
        let mut c = Case::new("claude-code", "debug = False\nkeep = 0\n");
        c.edit("discarded", "False", "True");
        if recorded {
            c.native.last_mut().unwrap()["toolUseResult"]["originalFile"] =
                json!("debug = False\nkeep = 0\n");
        }
        c.edit("undo", "True", "False");
        if recorded {
            c.native.last_mut().unwrap()["toolUseResult"]["originalFile"] =
                json!("debug = True\nkeep = 0\n");
        }
        c.edit("kept", "keep = 0", "keep = 1");
        c.commit("debug = True\nkeep = 1\n");
        let out = c.convert();
        c.check(&out, &[None, Some("kept")]);
    }
}

#[test]
fn c3_later_undo_after_the_commit_does_not_erase_the_committed_edit() {
    let mut c = Case::new("claude-code", "debug = False\n");
    c.edit("kept", "False", "True");
    c.commit("debug = True\n");
    c.edit("later-undo", "True", "False");
    let out = c.convert();
    c.check(&out, &[Some("kept")]);
}

#[test]
fn c4_identical_person_retyping_is_indistinguishable_from_recorded_text() {
    let mut c = Case::new("claude-code", "debug = False\n");
    c.edit("identical", "False", "True");
    // A checkout and identical person retyping have no observation in ASR.
    run("git", &["checkout", "--", "file.py"], &c.repo());
    c.commit("debug = True\n");
    let out = c.convert();
    c.check(&out, &[Some("identical")]);

    let mut c = Case::new("claude-code", "baseline\n");
    run("git", &["rm", "file.py"], &c.repo());
    run_at(
        "git",
        &[
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "Delete baseline",
        ],
        &c.repo(),
        c.tick(),
    );
    c.write("#!/usr/bin/env python3\nimport json\nprint('agent')\n");
    c.native.last_mut().unwrap()["toolUseResult"]["type"] = json!("create");
    c.commit("#!/usr/bin/env python3\nimport json\nprint('person')\n");
    let out = c.convert();
    // These are matches of text evidence, not proof of the person's authorship.
    c.check(&out, &[Some("write"), Some("write"), None]);
}

#[test]
fn reviewer_correct_claude_rename_and_person_neighbor_changes_stay_correct() {
    let mut c = Case::new("claude-code", "first = 0\nsecond = 0\n");
    c.edit("first", "first = 0\nsecond = 0", "first = 1\nsecond = 1");
    c.commit("first = 1\nsecond = 1\n");
    c.edit("second", "second = 1", "second = 2");
    c.commit("first = 1\nsecond = 2\n");
    run("git", &["mv", "file.py", "renamed.py"], &c.repo());
    run_at(
        "git",
        &[
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "Rename file",
        ],
        &c.repo(),
        c.tick(),
    );
    let out = c.convert();
    c.check_file(&out, "renamed.py", &[Some("first"), Some("second")]);
    fs::write(c.repo().join("renamed.py"), "first = 1\nsecond = 3\n").unwrap();
    run("git", &["add", "renamed.py"], &c.repo());
    run_at(
        "git",
        &[
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "Person edit after rename",
        ],
        &c.repo(),
        c.tick(),
    );
    c.check_file(&out, "renamed.py", &[Some("first"), None]);
}

#[test]
fn timestamps_missing_invalid_or_inside_clock_margin_stay_unknown() {
    for ts in [
        None,
        Some("invalid"),
        Some("2026-01-01T00:01:01Z"),
        Some("2026-01-01T00:02:59Z"),
        Some("2026-01-01T00:03:01Z"),
    ] {
        let mut c = Case::new("claude-code", "debug = False\n");
        c.edit("flag", "False", "True");
        for r in &mut c.native {
            match ts {
                Some(ts) => {
                    r["timestamp"] = json!(ts);
                }
                None => {
                    r.as_object_mut().unwrap().remove("timestamp");
                }
            }
        }
        c.commit("debug = True\n");
        let out = c.convert();
        c.check(&out, &[None]);
    }
}

#[test]
fn reviewer_two_sessions_in_separate_or_shared_commits_keep_correct_evidence() {
    for separate in [false, true] {
        let mut c = Case::new("claude-code", "debug = False\n");
        c.edit("first", "False", "True");
        if separate {
            c.commit("debug = True\n");
            c.commit("debug = False\n");
        }
        c.native.push(json!({"type":"user","uuid":"second-prompt","sessionId":"second-session","cwd":c.repo(),"origin":{"kind":"human"},"message":{"role":"user","content":"Redo the setting."}}));
        // A person's unrecorded reset separates the same replacement in two
        // independent sessions. No cross-session order is inferred from times.
        c.contents = "debug = False\n".into();
        c.edit("second", "False", "True");
        c.commit("debug = True\n");
        let out = c.convert();
        let result: Value = serde_json::from_str(&run(
            env!("CARGO_BIN_EXE_asr"),
            &[
                "blame",
                "file.py",
                "--line",
                "1",
                "--repo",
                c.repo().to_str().unwrap(),
                "--sessions",
                out.to_str().unwrap(),
            ],
            &root(),
        ))
        .unwrap();
        if separate {
            assert_eq!(result["editStatus"], "matched");
            assert!(result["editedBy"][0]["call"]
                .as_str()
                .unwrap()
                .ends_with("#second"));
        } else {
            assert_eq!(result["editStatus"], "unresolved");
            assert_eq!(result["editedBy"].as_array().unwrap().len(), 2);
        }
        println!(
            "{}",
            json!({"reviewerCase":"two-sessions-reset","correct":u32::from(separate),"unknown":0,"unresolved":u32::from(!separate),"wrong":0})
        );
    }
    let mut c = Case::new("claude-code", "count = 0\n");
    c.edit("first", "count = 0", "count = 1");
    c.commit("count = 1\n");
    c.native.push(json!({"type":"user","uuid":"second-prompt","sessionId":"second-session","cwd":c.repo(),"origin":{"kind":"human"},"message":{"role":"user","content":"Increase the count."}}));
    c.edit("second", "count = 1", "count = 2");
    c.commit("count = 2\n");
    let out = c.convert();
    c.check(&out, &[Some("second")]);
}

#[test]
fn reviewer_codex_partial_edits_reject_other_flags_and_person_moves() {
    let mut c = Case::new("codex", "debug = False\ncache = True\n");
    c.patch(
        "flag",
        "@@ -1,2 +1,2 @@\n-debug = False\n+debug = True\n cache = True\n",
    );
    c.commit("debug = True\ncache = True\n");
    c.commit("debug = True\ncache = False\n");
    c.commit("debug = True\ncache = True\n");
    let out = c.convert();
    c.check(&out, &[Some("flag"), None]);
    c.commit("cache = True\ndebug = True\n");
    c.check(&out, &[None, None]);
}

#[test]
fn reviewer_formatter_after_committed_write_can_verify_parent_context() {
    let mut c = Case::new("claude-code", "baseline = 0\n");
    c.write("values=[1,2]\nkeep=0\n");
    c.commit("values=[1,2]\nkeep=0\n");
    c.commit("values = [1, 2]\nkeep = 0\n");
    c.edit("formatted", "values = [1, 2]", "values = [1, 2, 3]");
    c.commit("values = [1, 2, 3]\nkeep = 0\n");
    let out = c.convert();
    c.check(&out, &[Some("formatted"), None]);
}

#[test]
fn reviewer_squash_preserves_agent_lines_but_excludes_person_fixup_and_main_lines() {
    let mut c = Case::new(
        "claude-code",
        "agent = 0\nfixup = 0\n# one\n# two\n# three\n# four\n# five\n# six\nmain = 0\n",
    );
    let branch = run("git", &["branch", "--show-current"], &c.repo());
    run("git", &["checkout", "-qb", "feature"], &c.repo());
    c.edit("agent", "agent = 0\nfixup = 0", "agent = 1\nfixup = 1");
    c.commit("agent = 1\nfixup = 1\n# one\n# two\n# three\n# four\n# five\n# six\nmain = 0\n");
    c.commit("agent = 1\nfixup = 2\n# one\n# two\n# three\n# four\n# five\n# six\nmain = 0\n");
    run("git", &["checkout", "-q", branch.trim()], &c.repo());
    // Commit timestamps establish the main baseline before the recorded edit.
    c.clock.set(1767225650);
    c.commit("agent = 0\nfixup = 0\n# one\n# two\n# three\n# four\n# five\n# six\nmain = 1\n");
    c.clock.set(1767226000);
    run("git", &["merge", "--squash", "feature"], &c.repo());
    c.commit("agent = 1\nfixup = 2\n# one\n# two\n# three\n# four\n# five\n# six\nmain = 1\n");
    let out = c.convert();
    c.check(
        &out,
        &[
            Some("agent"),
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        ],
    );
}

#[test]
fn c1_old_short_edit_is_not_a_competitor_for_a_second_sessions_other_flag() {
    let mut c = Case::new("claude-code", "debug = False\ncache = True\n");
    c.edit("debug", "False", "True");
    c.commit("debug = True\ncache = True\n");
    c.commit("debug = True\ncache = False\n");
    c.native.push(json!({"type":"user","uuid":"second-prompt","sessionId":"second-session","cwd":c.repo(),"origin":{"kind":"human"},"message":{"role":"user","content":"Enable the cache."}}));
    c.edit("cache", "False", "True");
    c.commit("debug = True\ncache = True\n");
    let out = c.convert();
    c.check(&out, &[Some("debug"), Some("cache")]);
}

#[test]
fn an_unrelated_parent_commit_does_not_reset_the_file_time_window() {
    let mut c = Case::new("claude-code", "debug = False\n");
    c.edit("flag", "False", "True");
    fs::write(c.repo().join("other.txt"), "person\n").unwrap();
    run("git", &["add", "other.txt"], &c.repo());
    run_at(
        "git",
        &[
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "Unrelated person file",
        ],
        &c.repo(),
        c.tick(),
    );
    c.commit("debug = True\n");
    let out = c.convert();
    c.check(&out, &[Some("flag")]);
}

#[test]
fn reviewer_unobserved_rename_and_edit_in_one_commit_stays_unknown() {
    let mut c = Case::new("claude-code", "debug = False\n");
    c.edit("flag", "False", "True");
    fs::write(c.repo().join("file.py"), "debug = True\n").unwrap();
    run("git", &["mv", "file.py", "renamed.py"], &c.repo());
    run_at(
        "git",
        &[
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "Person rename and agent edit",
        ],
        &c.repo(),
        c.tick(),
    );
    let out = c.convert();
    c.check_file(&out, "renamed.py", &[None]);
}

// Recheck 4 D1: author dates survive unrecorded rewrites by a person.
#[test]
fn d1_later_roundtrips_do_not_acquire_credit_after_amend_rebase_or_cherry_pick() {
    for rewrite in ["amend", "rebase", "cherry-pick"] {
        for original in [false, true] {
            let mut c = Case::new("claude-code", "retries = 1\n");
            let base = run("git", &["rev-parse", "HEAD"], &c.repo());
            c.commit("retries = 3\n");
            let person = run("git", &["rev-parse", "HEAD"], &c.repo());
            c.edit("away", "3", "5");
            c.edit("back", "5", "3");
            if original {
                for r in &mut c.native {
                    if r["toolUseResult"]["oldString"] == "3" {
                        r["toolUseResult"]["originalFile"] = json!("retries = 3\n");
                    } else if r["toolUseResult"]["oldString"] == "5" {
                        r["toolUseResult"]["originalFile"] = json!("retries = 5\n");
                    }
                }
            }
            let at = c.tick();
            match rewrite {
                "amend" => {
                    run_at(
                        "git",
                        &[
                            "-c",
                            "commit.gpgsign=false",
                            "commit",
                            "--amend",
                            "-qm",
                            "Message only",
                        ],
                        &c.repo(),
                        at,
                    );
                }
                _ => {
                    run(
                        "git",
                        &["checkout", "-qb", "upstream", base.trim()],
                        &c.repo(),
                    );
                    fs::write(c.repo().join("other.txt"), "main work\n").unwrap();
                    run("git", &["add", "other.txt"], &c.repo());
                    run_at(
                        "git",
                        &["-c", "commit.gpgsign=false", "commit", "-qm", "Upstream"],
                        &c.repo(),
                        at,
                    );
                    if rewrite == "cherry-pick" {
                        run_at(
                            "git",
                            &["-c", "commit.gpgsign=false", "cherry-pick", person.trim()],
                            &c.repo(),
                            at + 60,
                        );
                    } else {
                        run("git", &["checkout", "-q", "-"], &c.repo());
                        run_at("git", &["rebase", "upstream"], &c.repo(), at + 60);
                    }
                }
            }
            let out = c.convert();
            c.check(&out, &[None]);
        }
    }
}

#[test]
fn d2_first_observation_blocks_skewed_roundtrips_from_original_write_and_old_text() {
    for original in [false, true] {
        for skew in [-600_i64, 3600] {
            let mut c = Case::new("claude-code", "retries = 1\n");
            c.clock.set(c.clock.get() + 7200);
            c.commit("retries = 3\n");
            let commit_clock = c.clock.get();
            c.clock.set(commit_clock - skew.abs());
            if !original {
                c.write("retries = 3\n");
            }
            c.edit("away", "3", "5");
            c.native.last_mut().unwrap()["toolUseResult"]["originalFile"] = if original {
                json!("retries = 3\n")
            } else {
                Value::Null
            };
            c.edit("back", "5", "3");
            if original {
                c.native.last_mut().unwrap()["toolUseResult"]["originalFile"] =
                    json!("retries = 5\n");
            }
            // Both a slow recording clock and a fast committing clock put
            // these records inside the apparent window.
            let out = c.convert();
            c.check(&out, &[None]);
        }
    }
}

#[test]
fn d3_context_free_partial_edits_cannot_attach_to_a_persons_other_flag() {
    for plain in [false, true] {
        let mut c = Case::new("claude-code", "debug = False\ncache = True\n");
        c.contents = "debug = True\ncache = False\n".into();
        c.edit("cache", "False", "True");
        c.native.last_mut().unwrap()["toolUseResult"]
            .as_object_mut()
            .unwrap()
            .remove("structuredPatch");
        c.commit("debug = True\ncache = True\n");
        let out = c.convert();
        if plain {
            for entry in fs::read_dir(&out).unwrap() {
                let file = entry.unwrap().path();
                let records = fs::read_to_string(&file)
                    .unwrap()
                    .lines()
                    .map(|line| {
                        let mut r: Value = serde_json::from_str(line).unwrap();
                        r.as_object_mut().unwrap().remove("_meta");
                        format!("{r}\n")
                    })
                    .collect::<String>();
                fs::write(file, records).unwrap();
            }
            run(
                "node",
                &[
                    root()
                        .join("tools/validator/bin/asr-validate.js")
                        .to_str()
                        .unwrap(),
                    "--summary",
                    out.to_str().unwrap(),
                ],
                &root(),
            );
        }
        c.check(&out, &[None, None]);
    }
}

#[test]
fn d4_other_sessions_and_subagents_undo_the_original_origin() {
    for agent in ["claude-code", "codex"] {
        for original in [false, true] {
            for subagent in [false, true] {
                let mut c = Case::new(agent, "debug = False\n");
                if agent == "claude-code" {
                    c.edit("first", "False", "True");
                    if original {
                        c.native.last_mut().unwrap()["toolUseResult"]["originalFile"] =
                            json!("debug = False\n");
                    }
                } else {
                    c.patch("first", "@@ -1 +1 @@\n-debug = False\n+debug = True\n");
                }
                c.commit("debug = True\n");
                let out = c.convert();
                // The commit date is deliberately later than the undo. The
                // person's eventual retyping has the same tree as this commit.
                run_at(
                    "git",
                    &[
                        "-c",
                        "commit.gpgsign=false",
                        "commit",
                        "--amend",
                        "--reset-author",
                        "--no-edit",
                        "-q",
                    ],
                    &c.repo(),
                    c.clock.get() + 600,
                );
                let parent = if subagent {
                    json!({"kind":"subagent","session":format!("{agent}:synthetic-replay")})
                } else {
                    Value::Null
                };
                let mut header = json!({"type":"session","id":"header","formatVersion":"0.1","agent":{"name":agent},"sessionId":"undo-session","cwd":c.repo(),"producer":{"name":"synthetic","version":"1","method":"native"}});
                if subagent {
                    header["parent"] = parent;
                }
                let mut undo = json!({"type":"file_change","id":"undo","ts":chrono::DateTime::from_timestamp(c.clock.get() + 60,0).unwrap().to_rfc3339(),"path":"file.py","op":"modify","status":"applied","edits":[{"oldText":"debug = True\n","newText":"debug = False\n"}]});
                if original {
                    undo["before"] = json!({"text":"debug = True\n"});
                }
                fs::write(out.join("undo.jsonl"), format!("{header}\n{undo}\n")).unwrap();
                run(
                    "node",
                    &[
                        root()
                            .join("tools/validator/bin/asr-validate.js")
                            .to_str()
                            .unwrap(),
                        "--summary",
                        out.to_str().unwrap(),
                    ],
                    &root(),
                );
                c.check(&out, &[None]);
            }
        }
    }
}

#[test]
fn first_read_and_untimed_other_session_removals_are_clock_free_vetoes() {
    let mut c = Case::new("claude-code", "retries = 1\n");
    c.clock.set(c.clock.get() + 600);
    c.commit("retries = 3\n");
    c.clock.set(c.clock.get() - 300);
    c.claude(
        "read",
        "Read",
        json!({"file_path":c.repo().join("file.py")}),
        Value::Null,
    );
    c.native.last_mut().unwrap()["message"]["content"][0]["content"] = json!("retries = 3\n");
    c.edit("away", "3", "5");
    c.edit("back", "5", "3");
    let out = c.convert();
    c.check(&out, &[None]);
}

#[test]
fn d4_generated_skewed_cross_session_undo_cannot_leave_an_earlier_agent_credited() {
    for undo_time in [
        None,
        Some("2026-01-01T00:00:01Z"),
        Some("2026-01-01T01:00:00Z"),
    ] {
        let mut c = Case::new("claude-code", "debug = False\n");
        c.edit("first", "False", "True");
        c.commit("debug = True\n");
        let out = c.convert();
        let header = json!({"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"claude-code"},"sessionId":"skewed-undo","cwd":c.repo(),"producer":{"name":"synthetic","version":"1","method":"native"}});
        let mut undo = json!({"type":"file_change","id":"undo","path":"file.py","op":"modify","status":"applied","edits":[{"oldText":"debug = True\n","newText":"debug = False\n"}]});
        if let Some(ts) = undo_time {
            undo["ts"] = json!(ts);
        }
        fs::write(out.join("undo.jsonl"), format!("{header}\n{undo}\n")).unwrap();
        run(
            "node",
            &[
                root()
                    .join("tools/validator/bin/asr-validate.js")
                    .to_str()
                    .unwrap(),
                "--summary",
                out.to_str().unwrap(),
            ],
            &root(),
        );
        c.check(&out, &[None]);
    }
}

#[test]
fn recheck4_mixed_sessions_stale_writes_and_partial_staging_are_conservative() {
    for scenario in [
        "separate-lines",
        "adjacent-interleave",
        "stale-write",
        "partial-stage",
        "unstaged-undo",
        "person-index",
        "person-overlay",
        "excluded-agent",
    ] {
        let mut c = Case::new("claude-code", "first = 0\nsecond = 0\nthird = 0\n");
        c.edit("first", "first = 0", "first = 1");
        if scenario == "adjacent-interleave" {
            c.native.push(json!({"type":"user","uuid":"child-prompt","sessionId":"second","cwd":c.repo(),"message":{"role":"user","content":"Edit the next line."}}));
            c.edit("second", "second = 0", "second = 1");
            c.edit("again", "first = 1", "first = 2");
        } else if scenario == "stale-write" {
            c.native.push(json!({"type":"user","uuid":"parallel-prompt","sessionId":"parallel","cwd":c.repo(),"message":{"role":"user","content":"Write an older snapshot."}}));
            c.write("first = 0\nsecond = 2\nthird = 0\n");
        } else if scenario == "unstaged-undo" {
            c.edit("undo", "first = 1", "first = 0");
        } else if scenario != "excluded-agent" {
            if scenario == "separate-lines" {
                c.native.push(json!({"type":"user","uuid":"other-prompt","sessionId":"other","cwd":c.repo(),"message":{"role":"user","content":"Edit the other line."}}));
            }
            c.edit("second", "second = 0", "second = 1");
        }
        let contents = match scenario {
            "adjacent-interleave" => "first = 2\nsecond = 1\nthird = 3\n",
            "stale-write" => "first = 1\nsecond = 2\nthird = 3\n",
            "partial-stage" => "first = 1\nsecond = 0\nthird = 3\n",
            "unstaged-undo" => "first = 1\nsecond = 0\nthird = 0\n",
            "person-index" | "person-overlay" => "first = person\nsecond = 1\nthird = 0\n",
            "excluded-agent" => "first = 0\nsecond = 0\nthird = person\n",
            _ => "first = 1\nsecond = 1\nthird = 3\n",
        };
        let out = c.convert();
        c.commit(contents);
        if scenario == "partial-stage" {
            fs::write(
                c.repo().join("file.py"),
                "first = 1\nsecond = 1\nthird = 3\n",
            )
            .unwrap();
        } else if scenario == "unstaged-undo" {
            fs::write(
                c.repo().join("file.py"),
                "first = 0\nsecond = 0\nthird = 0\n",
            )
            .unwrap();
        }
        let expected = match scenario {
            "excluded-agent" => vec![None, None, None],
            "person-index" | "person-overlay" => vec![None, Some("second"), None],
            "unstaged-undo" => vec![None, None, None],
            "adjacent-interleave" => vec![Some("again"), Some("second"), None],
            _ => vec![Some("first"), Some("second"), None],
        };
        c.check(&out, &expected);
        if scenario == "partial-stage" {
            c.commit("first = 1\nsecond = 1\nthird = 3\n");
            c.check(&out, &[Some("first"), None, None]);
        }
    }
}

#[test]
fn recheck4_crlf_autocrlf_whitespace_and_context_variants_never_credit_person_lines() {
    for original in [false, true] {
        for variant in [
            "crlf",
            "autocrlf",
            "convert-lf",
            "trailing-space",
            "tab",
            "roundtrip",
            "reindent",
        ] {
            let before = if matches!(variant, "crlf" | "autocrlf" | "convert-lf") {
                "value = 0\r\nkeep = 0\r\n"
            } else {
                "value = 0\nkeep = 0\n"
            };
            let mut c = Case::new("claude-code", before);
            if variant == "autocrlf" {
                run("git", &["config", "core.autocrlf", "true"], &c.repo());
            }
            let (old, new) = if variant == "reindent" {
                ("value = 0", "    value = 0")
            } else {
                ("value = 0", "value = 1")
            };
            c.edit("agent", old, new);
            if original {
                c.native.last_mut().unwrap()["toolUseResult"]["originalFile"] = json!(before);
            }
            let out = c.convert();
            let contents = match variant {
                "crlf" | "autocrlf" => "value = 1\r\nkeep = person\r\n",
                "trailing-space" => "value = 1 \nkeep = 0\n",
                "tab" => "\tvalue = 1\nkeep = 0\n",
                "reindent" => "    value = 0\nkeep = 0\n",
                _ => "value = 1\nkeep = 0\n",
            };
            c.commit(contents);
            let expected = if matches!(variant, "crlf" | "autocrlf" | "reindent" | "roundtrip") {
                Some("agent")
            } else {
                None
            };
            c.check(&out, &[expected, None]);
            if variant == "roundtrip" {
                c.commit("value = 1 \nkeep = 0\n");
                c.commit("value = 1\nkeep = 0\n");
                c.check(&out, &[None, None]);
            }
        }
    }
    for context in ["keep = person", "keep = 0 ", "keep = ’0’"] {
        let mut c = Case::new("codex", "value = 0\nkeep = 0\n");
        c.patch(
            "agent",
            &format!("@@ -1,2 +1,2 @@\n-value = 0\n+value = 1\n {context}\n"),
        );
        c.commit("value = 1\nkeep = person\n");
        let out = c.convert();
        c.check(&out, &[None, None]);
    }
}

#[test]
fn recheck4_rewrites_keep_person_lines_unknown_and_recheck_surviving_agent_hunks() {
    for scenario in [
        "agent-amended-into-person",
        "person-amends-agent",
        "agent-rebase-same-file",
        "agent-rebase-other-file",
        "agent-cherry-pick",
        "agent-cherry-pick-x",
        "trailing-space-amend",
    ] {
        let mut c = Case::new(
            "claude-code",
            "retries = 1\n# one\n# two\n# three\n# four\n# five\nother = 0\n",
        );
        let base = run("git", &["rev-parse", "HEAD"], &c.repo());
        if matches!(
            scenario,
            "agent-amended-into-person" | "trailing-space-amend"
        ) {
            c.commit(if scenario == "trailing-space-amend" {
                "retries = 3 \n# one\n# two\n# three\n# four\n# five\nother = 0\n"
            } else {
                "retries = 3\n# one\n# two\n# three\n# four\n# five\nother = 0\n"
            });
            if scenario == "trailing-space-amend" {
                c.edit("strip", "3 ", "3");
                c.edit("restore", "3", "3 ");
            } else {
                c.edit("other", "other = 0", "other = 1");
                fs::write(c.repo().join("file.py"), &c.contents).unwrap();
                run("git", &["add", "file.py"], &c.repo());
            }
            run_at(
                "git",
                &[
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "--amend",
                    "-qm",
                    "Amended",
                ],
                &c.repo(),
                c.tick(),
            );
            let out = c.convert();
            c.check(&out, &[None; 7]);
            continue;
        }
        c.edit("agent", "retries = 1", "retries = 3");
        c.commit("retries = 3\n# one\n# two\n# three\n# four\n# five\nother = 0\n");
        let original = run("git", &["rev-parse", "HEAD"], &c.repo());
        if scenario == "person-amends-agent" {
            fs::write(
                c.repo().join("file.py"),
                "retries = 3\n# one\n# two\n# three\n# four\n# five\nother = person\n",
            )
            .unwrap();
            run("git", &["add", "file.py"], &c.repo());
            run_at(
                "git",
                &[
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "--amend",
                    "-qm",
                    "Person addition",
                ],
                &c.repo(),
                c.tick(),
            );
        } else {
            run(
                "git",
                &["checkout", "-qb", "release", base.trim()],
                &c.repo(),
            );
            if scenario == "agent-rebase-same-file" {
                fs::write(
                    c.repo().join("file.py"),
                    "retries = 1\n# one\n# two\n# three\n# four\n# five\nother = person\n",
                )
                .unwrap();
            } else {
                fs::write(c.repo().join("elsewhere.txt"), "upstream\n").unwrap();
            }
            run("git", &["add", "."], &c.repo());
            run_at(
                "git",
                &[
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "-qm",
                    "Upstream change",
                ],
                &c.repo(),
                c.tick(),
            );
            if scenario.starts_with("agent-rebase") {
                run("git", &["checkout", "-q", "-"], &c.repo());
                run_at("git", &["rebase", "release"], &c.repo(), c.tick());
            } else if scenario.ends_with("-x") {
                run_at(
                    "git",
                    &[
                        "-c",
                        "commit.gpgsign=false",
                        "cherry-pick",
                        "-x",
                        original.trim(),
                    ],
                    &c.repo(),
                    c.tick(),
                );
            } else {
                run_at(
                    "git",
                    &["-c", "commit.gpgsign=false", "cherry-pick", original.trim()],
                    &c.repo(),
                    c.tick(),
                );
            }
        }
        let out = c.convert();
        c.check(&out, &[Some("agent"), None, None, None, None, None, None]);
    }
}

#[test]
fn recheck4_codex_apply_patch_symbol_anchors_cannot_credit_the_other_copy() {
    for person_copy in [false, true] {
        let mut c = Case::new("codex", "def a():\n    flag = False\n    return flag\n\ndef b():\n    flag = False \n    return flag\n");
        let ts = chrono::DateTime::from_timestamp(c.tick(), 0)
            .unwrap()
            .to_rfc3339();
        c.native.extend([
            json!({"timestamp":ts,"type":"response_item","payload":{"type":"custom_tool_call","call_id":"anchored","name":"apply_patch","input":"*** Begin Patch\n*** Update File: file.py\n@@ def b():\n-    flag = False\n+    flag = True\n     return flag\n*** End Patch\n"}}),
            json!({"timestamp":ts,"type":"event_msg","payload":{"type":"patch_apply_end","call_id":"anchored","success":true}}),
        ]);
        let final_state = if person_copy {
            "def a():\n    flag = True\n    return flag\n\ndef b():\n    flag = True\n    return flag\n"
        } else {
            "def a():\n    flag = False\n    return flag\n\ndef b():\n    flag = True\n    return flag\n"
        };
        c.commit(final_state);
        let out = c.convert();
        c.check(&out, &[None; 7]);
    }
}

#[test]
fn recheck4_index_and_worktree_divergence_does_not_invent_committed_origins() {
    for scenario in [
        "staged-agent-unstaged-undo",
        "staged-person-later-agent",
        "staged-other-person-line",
    ] {
        let mut c = Case::new("claude-code", "flag = 0\nother = 0\n");
        if scenario == "staged-agent-unstaged-undo" {
            c.edit("agent", "flag = 0", "flag = 1");
            fs::write(c.repo().join("file.py"), &c.contents).unwrap();
            run("git", &["add", "file.py"], &c.repo());
            c.edit("undo", "flag = 1", "flag = 0");
        } else {
            c.contents = if scenario == "staged-person-later-agent" {
                "flag = 3\nother = 0\n"
            } else {
                "flag = 0\nother = person\n"
            }
            .into();
            fs::write(c.repo().join("file.py"), &c.contents).unwrap();
            run("git", &["add", "file.py"], &c.repo());
            if scenario == "staged-person-later-agent" {
                c.edit("agent", "flag = 3", "flag = 5");
            } else {
                c.edit("agent", "flag = 0", "flag = 1");
            }
        }
        fs::write(c.repo().join("file.py"), &c.contents).unwrap();
        run_at(
            "git",
            &["-c", "commit.gpgsign=false", "commit", "-qm", "Index only"],
            &c.repo(),
            c.tick(),
        );
        let out = c.convert();
        // Query the committed tree, then commit the previously excluded work.
        run("git", &["checkout", "--", "file.py"], &c.repo());
        c.check(&out, &[None, None]);
        if scenario == "staged-person-later-agent" {
            c.commit("flag = 5\nother = 0\n");
            c.check(&out, &[None, None]);
        }
    }
}

#[test]
fn recheck4_parent_and_subagent_separate_overridden_and_undone_lines_stay_correct() {
    for agent in ["claude-code", "codex"] {
        for scenario in ["separate", "parent-overrides", "child-undo-parent-sets"] {
            let mut c = Case::new(agent, "first = 0\nsecond = 0\n");
            if scenario == "parent-overrides" {
                c.contents = "first = 1\nsecond = 0\n".into();
            }
            if agent == "claude-code" {
                if scenario == "parent-overrides" {
                    c.edit("parent", "first = 1", "first = 2");
                } else {
                    c.edit("parent", "first = 0", "first = 1");
                }
            } else if scenario == "parent-overrides" {
                c.patch(
                    "parent",
                    "@@ -1,2 +1,2 @@\n-first = 1\n+first = 2\n second = 0\n",
                );
            } else {
                c.patch(
                    "parent",
                    "@@ -1,2 +1,2 @@\n-first = 0\n+first = 1\n second = 0\n",
                );
            }
            let (before, after, final_state) = match scenario {
                "separate" => (
                    "first = 1\nsecond = 0\n",
                    "first = 1\nsecond = 1\n",
                    "first = 1\nsecond = 1\n",
                ),
                "parent-overrides" => (
                    "first = 0\nsecond = 0\n",
                    "first = 1\nsecond = 0\n",
                    "first = 2\nsecond = 0\n",
                ),
                _ => (
                    "first = 0\nsecond = 0\n",
                    "first = 1\nsecond = 0\n",
                    "first = 1\nsecond = 0\n",
                ),
            };
            c.commit(final_state);
            let out = c.convert();
            let parent = if agent == "claude-code" {
                "claude-code:synthetic-replay"
            } else {
                "codex:synthetic-replay"
            };
            let header = json!({"type":"session","id":"header","formatVersion":"0.1","agent":{"name":agent},"sessionId":"child","cwd":c.repo(),"producer":{"name":"synthetic","version":"1","method":"native"},"parent":{"kind":"subagent","session":parent}});
            let change = json!({"type":"file_change","id":"set","ts":"2026-01-01T00:02:10Z","path":"file.py","op":"modify","status":"applied","before":{"text":before},"after":{"text":after}});
            let mut records = format!("{header}\n{change}\n");
            if scenario == "child-undo-parent-sets" {
                let undo = json!({"type":"file_change","id":"undo","ts":"2026-01-01T00:02:20Z","path":"file.py","op":"modify","status":"applied","before":{"text":after},"after":{"text":before}});
                records.push_str(&format!("{undo}\n"));
            }
            fs::write(out.join("child.jsonl"), records).unwrap();
            run(
                "node",
                &[
                    root()
                        .join("tools/validator/bin/asr-validate.js")
                        .to_str()
                        .unwrap(),
                    "--summary",
                    out.to_str().unwrap(),
                ],
                &root(),
            );
            for line in [1, 2] {
                let result: Value = serde_json::from_str(&run(
                    env!("CARGO_BIN_EXE_asr"),
                    &[
                        "blame",
                        "file.py",
                        "--line",
                        &line.to_string(),
                        "--repo",
                        c.repo().to_str().unwrap(),
                        "--sessions",
                        out.to_str().unwrap(),
                    ],
                    &root(),
                ))
                .unwrap();
                if result["editStatus"] != "unknown" {
                    assert_eq!(result["editStatus"], "matched");
                    let expected = if scenario == "separate" && line == 2 {
                        format!("{agent}:child")
                    } else {
                        parent.to_owned()
                    };
                    assert_eq!(result["editedBy"][0]["session"], expected);
                }
            }
        }
    }
}

#[test]
fn writes_need_a_confirmed_new_path_or_consistent_original_and_native_states() {
    for original in [false, true] {
        let mut c = Case::new("claude-code", "");
        c.write("created = 1\n");
        c.native.last_mut().unwrap()["toolUseResult"]["type"] = json!("create");
        if original {
            c.native.last_mut().unwrap()["toolUseResult"]["originalFile"] = json!("");
            c.native.last_mut().unwrap()["toolUseResult"]["structuredPatch"] = json!([{"oldStart":0,"oldLines":0,"newStart":1,"newLines":1,"lines":["+different = 2"]}]);
        }
        c.commit("created = 1\n");
        let out = c.convert();
        c.check(&out, &[None]);
    }
}
