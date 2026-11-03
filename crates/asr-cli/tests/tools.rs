use serde_json::{json, Value};
use std::{
    fs,
    io::{Read, Write},
    net::TcpListener,
    path::{Path, PathBuf},
    process::{Command, Output},
    thread,
};
fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}
fn cli(args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_asr"))
        .args(args)
        .current_dir(root())
        .output()
        .unwrap()
}
fn ok(output: Output) -> Value {
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).unwrap()
}
fn write(path: &Path, records: &[Value]) {
    let mut f = fs::File::create(path).unwrap();
    for r in records {
        writeln!(f, "{}", r).unwrap();
    }
}
fn read(path: &Path) -> Vec<Value> {
    fs::read_to_string(path)
        .unwrap()
        .lines()
        .map(|s| asr_core::jsonl::decode(s).unwrap())
        .collect()
}
fn header() -> Value {
    json!({"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"com.example.agent"},"sessionId":"synthetic","producer":{"name":"fixture","version":"1","method":"native"}})
}
fn validate(path: &Path) {
    let o = Command::new("node")
        .arg(root().join("tools/validator/bin/asr-validate.js"))
        .arg("--summary")
        .arg(path)
        .output()
        .unwrap();
    assert!(
        o.status.success(),
        "{} {}",
        String::from_utf8_lossy(&o.stdout),
        String::from_utf8_lossy(&o.stderr)
    );
}
fn s(p: &Path) -> &str {
    p.to_str().unwrap()
}
#[test]
fn redact_masks_known_secrets_preserves_exact_numbers_and_never_overwrites() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("in.jsonl");
    let out = temp.path().join("out.jsonl");
    let secret = format!("sk-{}", "a".repeat(32));
    write(
        &input,
        &[
            header(),
            json!({"type":"message","id":"prompt","role":"user","author":"human","content":[{"type":"text","text":format!("secret {secret}")}],"_meta":{"com.example.fixture":{"apiKey":"synthetic-value","keep":9007199254740993u64,"personal":"synthetic-name"}}}),
        ],
    );
    let original = fs::read(&input).unwrap();
    let report = ok(cli(&[
        "redact",
        s(&input),
        "--out",
        s(&out),
        "--remove",
        "/_meta/com.example.fixture/personal",
    ]));
    assert_eq!(report["validated"], true);
    let records = read(&out);
    assert_eq!(
        records[0]["derivedFrom"]["sha256"],
        format!("{:x}", <sha2::Sha256 as sha2::Digest>::digest(&original))
    );
    assert_eq!(records[0]["producer"]["method"], "converter");
    assert_eq!(
        records[1]["_meta"]["com.example.fixture"]["keep"].to_string(),
        "9007199254740993"
    );
    assert!(records[1]["_meta"]["com.example.fixture"]
        .get("personal")
        .is_none());
    assert!(!fs::read_to_string(&out).unwrap().contains(&secret));
    assert_eq!(records[1]["truncated"], true);
    assert_eq!(fs::read(&input).unwrap(), original);
    assert_eq!(
        cli(&["redact", s(&input), "--out", s(&input)])
            .status
            .code(),
        Some(2)
    );
    assert_eq!(
        cli(&["redact", s(&input), "--out", s(&out)]).status.code(),
        Some(2)
    );
    validate(&out);
}
#[test]
fn redact_recovers_bad_lines_defers_tail_and_rejects_required_field_removal() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("in.jsonl");
    let out = temp.path().join("out.jsonl");
    fs::write(&input,format!("{}\n{{bad}}\n{}\n{{\"tail\":",header(),json!({"type":"message","id":"m","role":"user","content":[{"type":"text","text":"hello"}]}))).unwrap();
    let report = ok(cli(&[
        "redact",
        s(&input),
        "--out",
        s(&out),
        "--mask",
        "/content/*/text",
    ]));
    assert_eq!(report["sourceWarnings"].as_array().unwrap().len(), 2);
    let records = read(&out);
    assert_eq!(records.len(), 3);
    assert_eq!(records[1]["type"], "gap");
    assert_eq!(records[2]["content"][0]["text"], "[REDACTED]");
    validate(&out);
    let bad = temp.path().join("bad.jsonl");
    assert_eq!(
        cli(&["redact", s(&input), "--out", s(&bad), "--remove", "/role"])
            .status
            .code(),
        Some(2)
    );
    assert!(!bad.exists());
}
#[test]
fn redact_corpus() {
    let temp = tempfile::tempdir().unwrap();
    let mut files = Vec::new();
    for dir in ["samples", "examples"] {
        for entry in walkdir::WalkDir::new(root().join(dir)) {
            let entry = entry.unwrap();
            let p = entry.path();
            if entry.file_type().is_file()
                && p.extension().is_some_and(|e| e == "jsonl")
                && !p.to_string_lossy().ends_with(".annotations.jsonl")
            {
                let content = fs::read_to_string(p).unwrap();
                if content
                    .lines()
                    .next()
                    .and_then(|s| serde_json::from_str::<Value>(s).ok())
                    .is_some_and(|r| r["type"] == "session" && r["formatVersion"] == "0.1")
                {
                    files.push(p.to_owned());
                }
            }
        }
    }
    assert!(files.len() >= 16);
    for (i, input) in files.iter().enumerate() {
        let out = temp.path().join(format!("{i}.jsonl"));
        ok(cli(&["redact", s(input), "--out", s(&out)]));
        validate(&out);
    }
}
fn git(repo: &Path, args: &[&str]) -> String {
    let count = Command::new("git")
        .arg("-C")
        .arg(repo)
        .args(["rev-list", "--count", "HEAD"])
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .and_then(|n| n.trim().parse::<i64>().ok())
        .unwrap_or(0);
    let at = 1767225600 + count * 600;
    let o = Command::new("git")
        .arg("-C")
        .arg(repo)
        .args(args)
        .env("GIT_AUTHOR_DATE", format!("@{at} +0000"))
        .env("GIT_COMMITTER_DATE", format!("@{at} +0000"))
        .env("GIT_AUTHOR_NAME", "Synthetic")
        .env("GIT_AUTHOR_EMAIL", "synthetic@example.invalid")
        .env("GIT_COMMITTER_NAME", "Synthetic")
        .env("GIT_COMMITTER_EMAIL", "synthetic@example.invalid")
        .output()
        .unwrap();
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    String::from_utf8(o.stdout).unwrap().trim().to_owned()
}
struct Repo {
    temp: tempfile::TempDir,
    records: Vec<Value>,
    commit: String,
}
impl Repo {
    fn new() -> Self {
        let temp = tempfile::tempdir().unwrap();
        let p = temp.path();
        git(p, &["init", "-q"]);
        fs::write(p.join("file.txt"), "context\nold\n").unwrap();
        git(p, &["add", "file.txt"]);
        git(p, &["commit", "-qm", "baseline"]);
        fs::write(p.join("file.txt"), "context\nnew\n").unwrap();
        git(p, &["add", "file.txt"]);
        git(p, &["commit", "-qm", "change"]);
        let commit = git(p, &["rev-parse", "HEAD"]);
        let mut h = header();
        h["cwd"] = json!(s(p));
        h["repos"] = json!([{"path":s(p)}]);
        let records = vec![
            h,
            json!({"type":"message","id":"prompt","turnId":"t","role":"user","author":"human","origin":"prompt","content":[{"type":"text","text":"Change the second line"}]}),
            json!({"type":"inference","id":"inf","model":{"requested":"synthetic-model","id":"synthetic-served"}}),
            json!({"type":"tool_call","id":"call","callId":"edit","inferenceId":"inf","turnId":"t","name":"replace","input":{"old":"old","new":"new"}}),
            json!({"type":"approval","id":"approve","callId":"edit","decision":"approved","by":"user"}),
            json!({"type":"tool_result","id":"result","callId":"edit","status":"completed"}),
            json!({"type":"file_change","id":"change","ts":"2026-01-01T00:05:00Z","path":"file.txt","op":"modify","status":"applied","callId":"edit","before":{"text":"context\nold\n"},"after":{"text":"context\nnew\n"}}),
            json!({"type":"vcs","id":"commit","action":"commit","status":"completed","evidence":"observed","commit":commit,"subject":"change"}),
        ];
        Self {
            temp,
            records,
            commit,
        }
    }
    fn blame(&self, line: usize) -> Value {
        let p = self.temp.path();
        let sessions = p.join("session.jsonl");
        write(&sessions, &self.records);
        ok(cli(&[
            "blame",
            "file.txt",
            "--line",
            &line.to_string(),
            "--repo",
            s(p),
            "--sessions",
            s(&sessions),
        ]))
    }
}
#[test]
fn blame_separates_credits_links_prompt_model_and_approval() {
    let r = Repo::new();
    let b = r.blame(2);
    assert_eq!(b["editStatus"], "matched");
    assert_eq!(b["editedBy"][0]["model"]["kind"], "served");
    assert_eq!(b["editedBy"][0]["approvals"].as_array().unwrap().len(), 1);
    assert_eq!(b["editedBy"][0]["prompts"].as_array().unwrap().len(), 1);
    assert_eq!(b["committedBy"].as_array().unwrap().len(), 1);
    assert_eq!(b["proof"], false);
    let context = r.blame(1);
    assert!(context["editedBy"].as_array().unwrap().is_empty());
}
#[test]
fn blame_excludes_copies_and_dirty_context_and_keeps_person_edits() {
    let mut r = Repo::new();
    r.records[0]["parent"] =
        json!({"session":"com.example.agent:parent","kind":"fork","copiedThrough":"commit"});
    let b = r.blame(2);
    assert!(b["editedBy"].as_array().unwrap().is_empty());
    assert!(b["committedBy"].as_array().unwrap().is_empty());
    r.records[0].as_object_mut().unwrap().remove("parent");
    r.records[6]["before"]["text"] = json!("context\nnew\n");
    assert_eq!(r.blame(2)["editStatus"], "unknown");
    r.records[6].as_object_mut().unwrap().remove("before");
    assert_eq!(r.blame(2)["editStatus"], "unknown");
    r.records[6]["before"] = json!({"text":"context\nold\n"});
    r.records[6].as_object_mut().unwrap().remove("callId");
    r.records[6]["actor"] = json!("human");
    assert_eq!(r.blame(2)["editedBy"][0]["credit"], "person");
    r.records[7]["status"] = json!("failed");
    assert!(r.blame(2)["committedBy"].as_array().unwrap().is_empty());
}
#[test]
fn blame_prefix_verifies_subject_parents_reachability_and_status() {
    let mut r = Repo::new();
    r.records[7].as_object_mut().unwrap().remove("commit");
    r.records[7]["commitPrefix"] = json!(&r.commit[..7]);
    assert_eq!(r.blame(2)["committedBy"].as_array().unwrap().len(), 1);
    r.records[7]["subject"] = json!("wrong");
    assert!(r.blame(2)["committedBy"].as_array().unwrap().is_empty());
    r.records[7]["subject"] = json!("change");
    r.records[7]["parentCount"] = json!(2);
    assert!(r.blame(2)["committedBy"].as_array().unwrap().is_empty());
    r.records[7].as_object_mut().unwrap().remove("parentCount");
    r.records[7]["status"] = json!("unknown");
    assert!(r.blame(2)["committedBy"].as_array().unwrap().is_empty());
    r.records[7]["callId"] = json!("edit");
    assert_eq!(r.blame(2)["committedBy"].as_array().unwrap().len(), 1);
    r.records
        .push(json!({"type":"tool_call","id":"ambiguous","callId":"edit","name":"other"}));
    let b = r.blame(2);
    assert!(b["committedBy"].as_array().unwrap().is_empty());
    assert!(b["editedBy"][0]["call"].is_null());
    assert!(b["editedBy"][0]["approvals"].as_array().unwrap().is_empty());
}
#[test]
fn blame_rewrites_carry_original_credit_but_recheck_surviving_edits() {
    let mut r = Repo::new();
    git(r.temp.path(), &["commit", "--amend", "-qm", "rewritten"]);
    let next = git(r.temp.path(), &["rev-parse", "HEAD"]);
    r.records.push(json!({"type":"vcs","id":"rewrite","action":"amend","status":"completed","evidence":"observed","commit":next,"rewrites":[{"from":r.commit,"to":next}]}));
    let b = r.blame(2);
    assert_eq!(b["editedBy"].as_array().unwrap().len(), 1);
    assert_eq!(b["committedBy"].as_array().unwrap().len(), 2);
    assert_eq!(b["touched"].as_array().unwrap().len(), 1);
    fs::write(r.temp.path().join("file.txt"), "context\nother\n").unwrap();
    git(r.temp.path(), &["add", "file.txt"]);
    git(
        r.temp.path(),
        &["commit", "--amend", "-qm", "conflict resolution"],
    );
    let final_id = git(r.temp.path(), &["rev-parse", "HEAD"]);
    r.records[8]["commit"] = json!(final_id);
    r.records[8]["rewrites"][0]["to"] = json!(final_id);
    assert_eq!(r.blame(2)["editStatus"], "unknown");
}
#[test]
fn blame_replacements_patches_alternatives_and_repository_checks() {
    let mut r = Repo::new();
    r.records[6].as_object_mut().unwrap().remove("before");
    r.records[6].as_object_mut().unwrap().remove("after");
    r.records[6]["edits"] = json!([{"oldText":"context\nold\n","newText":"context\nnew\n"}]);
    assert_eq!(r.blame(2)["editStatus"], "matched");
    r.records[6].as_object_mut().unwrap().remove("edits");
    r.records[6]["patch"] =
        json!("--- a/file.txt\n+++ b/file.txt\n@@ -1,2 +1,2 @@\n context\n-old\n+new\n");
    assert_eq!(r.blame(2)["editStatus"], "matched");
    let mut late = r.records[6].clone();
    late["id"] = json!("later");
    r.records.push(late);
    // Reapplying an old patch without the intervening reset cannot explain
    // this commit from its parent.
    assert_eq!(r.blame(2)["editStatus"], "unknown");
    // The second recorded before-state removes the first edit before redoing it.
    assert_eq!(r.blame(2)["alternatives"].as_array().unwrap().len(), 0);
    r.records[0]["repos"][0]["path"] = json!("/work/unavailable");
    assert_eq!(r.blame(2)["editStatus"], "unknown");
    assert!(r.blame(2)["committedBy"].as_array().unwrap().is_empty());
}
fn serve(protocol: &str, response: Value, status: u16) -> (String, thread::JoinHandle<Value>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    let protocol = protocol.to_owned();
    let handle = thread::spawn(move || {
        listener.set_nonblocking(true).unwrap();
        let start = std::time::Instant::now();
        let mut stream = loop {
            match listener.accept() {
                Ok((s, _)) => break s,
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                    assert!(start.elapsed().as_secs() < 15, "request never arrived");
                    thread::sleep(std::time::Duration::from_millis(10));
                }
                Err(e) => panic!("{e}"),
            }
        };
        stream
            .set_read_timeout(Some(std::time::Duration::from_secs(10)))
            .unwrap();
        let mut raw = Vec::new();
        let (end, length) = loop {
            let mut bytes = [0; 4096];
            let n = stream.read(&mut bytes).unwrap();
            assert!(n > 0);
            raw.extend_from_slice(&bytes[..n]);
            if let Some(end) = raw.windows(4).position(|b| b == b"\r\n\r\n") {
                let headers = std::str::from_utf8(&raw[..end]).unwrap();
                assert!(headers.starts_with(if protocol == "openai" {
                    "POST /v1/chat/completions "
                } else {
                    "POST /v1/messages "
                }));
                let length = headers
                    .lines()
                    .find_map(|s| {
                        s.to_ascii_lowercase()
                            .strip_prefix("content-length: ")
                            .map(|n| n.parse::<usize>().unwrap())
                    })
                    .unwrap();
                break (end + 4, length);
            }
        };
        while raw.len() < end + length {
            let mut bytes = [0; 4096];
            let n = stream.read(&mut bytes).unwrap();
            assert!(n > 0);
            raw.extend_from_slice(&bytes[..n]);
        }
        let request = serde_json::from_slice(&raw[end..end + length]).unwrap();
        let body = response.to_string();
        write!(stream,"HTTP/1.1 {status} Result\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).unwrap();
        request
    });
    (format!("http://{addr}/v1"), handle)
}
fn provider(path: &Path, base: &str, protocol: &str) {
    fs::write(
        path,
        json!({"protocol":protocol,"baseUrl":base,"apiKey":"synthetic-key"}).to_string(),
    )
    .unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o600)).unwrap();
    }
}
fn replay_source(path: &Path) {
    fs::copy(
        Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/replay-source.jsonl"),
        path,
    )
    .unwrap();
}
#[test]
fn replay_completion_order_uses_tools_before_the_first_output() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("input.jsonl");
    replay_source(&input);
    let mut source = read(&input);
    let index = source
        .iter()
        .position(|r| r["type"] == "inference")
        .unwrap();
    source.insert(index, json!({"type":"session_info","id":"later-tools","tools":[{"name":"later-tool","inputSchema":{"type":"object"}}]}));
    source.insert(index + 1, json!({"type":"message","id":"later-prompt","role":"user","content":[{"type":"text","text":"later context"}]}));
    fs::write(
        &input,
        source.iter().map(|r| format!("{r}\n")).collect::<String>(),
    )
    .unwrap();
    let config = temp.path().join("provider.json");
    let out = temp.path().join("run.jsonl");
    let (base, server) = serve(
        "openai",
        json!({"id":"response","choices":[{"message":{"content":"variant answer"}}]}),
        200,
    );
    provider(&config, &base, "openai");
    let report = ok(cli(&[
        "replay",
        s(&input),
        "--inference",
        "selected",
        "--provider-settings",
        s(&config),
        "--out",
        s(&out),
    ]));
    let request = server.join().unwrap();
    assert_eq!(request["messages"].as_array().unwrap().len(), 2);
    assert_eq!(request["tools"][0]["function"]["name"], "shell");
    assert!(!request.to_string().contains("do not send"));
    assert!(!request.to_string().contains("later"));
    assert!(report["contextDetail"]
        .as_str()
        .unwrap()
        .contains("approximate"));
    let records = read(&out);
    assert!(records[0]["missing"]
        .as_array()
        .unwrap()
        .contains(&json!("replay_context")));
    assert!(!records
        .iter()
        .any(|r| r["copiedFrom"]["record"] == "original-output"
            || r["copiedFrom"]["record"] == "later-tools"));
    validate(&out);
}
#[test]
fn replay_openai_changes_system_model_settings_excludes_selected_output_and_never_executes_tools() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("input.jsonl");
    replay_source(&input);
    let config = temp.path().join("provider.json");
    let out = temp.path().join("run.jsonl");
    let system = temp.path().join("system.txt");
    fs::write(&system, "variant system").unwrap();
    let (base, server) = serve(
        "openai",
        json!({"id":"response-1","model":"served-model","choices":[{"finish_reason":"tool_calls","message":{"tool_calls":[{"id":"call-1","type":"function","function":{"name":"shell","arguments":"{\"command\":\"never execute\"}"}}]}}],"usage":{"prompt_tokens":10,"completion_tokens":0,"prompt_tokens_details":{"cached_tokens":2}}}),
        200,
    );
    provider(&config, &base, "openai");
    let report = ok(cli(&[
        "replay",
        s(&input),
        "--inference",
        "selected",
        "--provider-settings",
        s(&config),
        "--out",
        s(&out),
        "--model",
        "variant-model",
        "--system-prompt-file",
        s(&system),
        "--setting",
        "temperature=0.25",
        "--variant",
        "test",
        "--run-number",
        "2",
    ]));
    let request = server.join().unwrap();
    assert_eq!(request["model"], "variant-model");
    assert_eq!(request["temperature"], 0.25);
    assert_eq!(request["messages"][0]["content"], "variant system");
    assert!(!request.to_string().contains("do not send"));
    assert_eq!(request["tools"].as_array().unwrap().len(), 1);
    assert_eq!(report["requestFailed"], false);
    let records = read(&out);
    assert_eq!(records[0]["parent"]["kind"], "fork");
    assert_eq!(records[0]["parent"]["record"], "prompt");
    assert_eq!(
        records[0]["_meta"]["org.agentsessionrecord.tools"]["run"],
        2
    );
    assert!(records.iter().any(|r| r["type"] == "tool_call"));
    assert!(!records.iter().any(|r| r["type"] == "tool_result"));
    assert!(records
        .iter()
        .filter(|r| r["type"] == "inference" && r.get("copiedFrom").is_none())
        .any(|r| r["usage"]["outputTokens"] == 0));
    validate(&out);
}
#[test]
fn replay_anthropic_usage_is_inclusive_and_signatures_are_excluded() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("input.jsonl");
    replay_source(&input);
    let config = temp.path().join("provider.json");
    let out = temp.path().join("run.jsonl");
    let (base, server) = serve(
        "anthropic",
        json!({"id":"message-1","model":"synthetic-served","stop_reason":"end_turn","content":[{"type":"thinking","thinking":"synthetic reasoning","signature":"opaque-do-not-store"},{"type":"text","text":"synthetic answer"}],"usage":{"input_tokens":10,"cache_read_input_tokens":2,"cache_creation_input_tokens":3,"output_tokens":4}}),
        200,
    );
    provider(&config, &base, "anthropic");
    ok(cli(&[
        "replay",
        s(&input),
        "--inference",
        "selected",
        "--provider-settings",
        s(&config),
        "--out",
        s(&out),
    ]));
    let request = server.join().unwrap();
    assert_eq!(request["max_tokens"], 100);
    assert_eq!(request["temperature"], 0);
    assert_eq!(request["system"][0]["text"], "original system");
    let records = read(&out);
    assert_eq!(
        records.iter().find(|r| r["type"] == "inference").unwrap()["usage"]["inputTokens"],
        15
    );
    assert!(!fs::read_to_string(&out)
        .unwrap()
        .contains("opaque-do-not-store"));
    let reasoning = &records.iter().find(|r| r["id"] == "replay-reply").unwrap()["content"][0];
    assert_eq!(reasoning["visibility"], "summary");
    assert_eq!(reasoning["summary"], json!(["synthetic reasoning"]));
    assert!(reasoning.get("text").is_none());
    validate(&out);
}
#[test]
fn replay_records_http_failures_and_rejects_insecure_configuration() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("input.jsonl");
    replay_source(&input);
    let config = temp.path().join("provider.json");
    let out = temp.path().join("run.jsonl");
    let (base, server) = serve(
        "openai",
        json!({"error":"do not retain server error content"}),
        401,
    );
    provider(&config, &base, "openai");
    let output = cli(&[
        "replay",
        s(&input),
        "--inference",
        "selected",
        "--provider-settings",
        s(&config),
        "--out",
        s(&out),
    ]);
    assert_eq!(output.status.code(), Some(1));
    server.join().unwrap();
    assert!(!fs::read_to_string(&out).unwrap().contains("server error"));
    validate(&out);
    provider(&config, "http://example.invalid/v1", "openai");
    let other = temp.path().join("other.jsonl");
    let output = cli(&[
        "replay",
        s(&input),
        "--inference",
        "selected",
        "--provider-settings",
        s(&config),
        "--out",
        s(&other),
    ]);
    assert_eq!(output.status.code(), Some(2));
    assert!(!other.exists());
}

#[test]
fn blame_competing_sessions_stay_unresolved_and_copied_records_have_no_credit() {
    let mut r = Repo::new();
    let p = r.temp.path();
    let one = p.join("one.jsonl");
    let two = p.join("two.jsonl");
    write(&one, &r.records);
    r.records[0]["sessionId"] = json!("competing");
    write(&two, &r.records);
    let b = ok(cli(&[
        "blame",
        "file.txt",
        "--line",
        "2",
        "--repo",
        s(p),
        "--sessions",
        s(&one),
        "--sessions",
        s(&two),
    ]));
    assert_eq!(b["editStatus"], "unresolved");
    assert_eq!(b["editedBy"].as_array().unwrap().len(), 2);
    r.records[6]["copiedFrom"] = json!({"record":"source-change"});
    r.records[7]["copiedFrom"] = json!({"session":"com.example.agent:source"});
    let b = r.blame(2);
    assert_eq!(b["editStatus"], "unknown");
    assert!(b["committedBy"].as_array().unwrap().is_empty());
}
#[test]
fn blame_carries_moves_reads_blob_states_and_does_not_credit_worktree_lines() {
    let mut r = Repo::new();
    git(r.temp.path(), &["mv", "file.txt", "moved.txt"]);
    fs::write(r.temp.path().join("moved.txt"), "context\nold\n").unwrap();
    git(r.temp.path(), &["add", "moved.txt"]);
    git(r.temp.path(), &["commit", "-qm", "move and change"]);
    let p = r.temp.path();
    let current = git(p, &["rev-parse", "HEAD"]);
    let blob = git(p, &["rev-parse", &format!("{current}:moved.txt")]);
    r.records[6]["ts"] = json!("2026-01-01T00:15:00Z");
    // The earlier source edit added old. The later move carries it to the new path.
    r.records[6]["before"] = json!({"text":"context\nnew\n"});
    r.records[6]["after"] = json!({"objectId":blob});
    r.records.push(json!({"type":"file_change","id":"move","ts":"2026-01-01T00:16:00Z","path":"moved.txt","oldPath":"file.txt","op":"move","status":"applied","actor":"harness"}));
    let session = p.join("session.jsonl");
    write(&session, &r.records);
    let b = ok(cli(&[
        "blame",
        "moved.txt",
        "--line",
        "2",
        "--repo",
        s(p),
        "--sessions",
        s(&session),
    ]));
    // A rename and a content change without a replayable destination parent
    // cannot explain the introducing hunk.
    assert_eq!(b["editStatus"], "unknown");
    fs::write(p.join("moved.txt"), "context\nuncommitted\n").unwrap();
    let b = ok(cli(&[
        "blame",
        "moved.txt",
        "--line",
        "2",
        "--repo",
        s(p),
        "--sessions",
        s(&session),
    ]));
    assert_eq!(b["editStatus"], "unknown");
    assert!(b["committedBy"].as_array().unwrap().is_empty());
}
#[test]
fn blame_annotation_rewrites_apply_corrections_without_granting_credit() {
    let r = Repo::new();
    let p = r.temp.path();
    git(p, &["commit", "--amend", "-qm", "rewritten"]);
    let successor = git(p, &["rev-parse", "HEAD"]);
    let session = p.join("session.jsonl");
    write(&session, &r.records);
    let annotations = p.join("rewrite.annotations.jsonl");
    let a = json!({"type":"annotation","id":"rewrite","session":"com.example.agent:synthetic","kind":"vcs","at":"2026-10-31T12:00:00Z","source":{"name":"synthetic"},"data":{"action":"rebase","status":"completed","evidence":"observed","rewrites":[{"from":r.commit,"to":successor}]}});
    write(&annotations, std::slice::from_ref(&a));
    let b = ok(cli(&[
        "blame",
        "file.txt",
        "--line",
        "2",
        "--repo",
        s(p),
        "--sessions",
        s(&session),
        "--annotations",
        s(&annotations),
    ]));
    assert_eq!(b["committedBy"].as_array().unwrap().len(), 1);
    assert_eq!(b["committedBy"][0]["commit"], r.commit);
    let mut correction = a.clone();
    correction["id"] = json!("correction");
    correction["supersedes"] = json!("rewrite");
    correction["data"]["status"] = json!("failed");
    write(&annotations, &[a, correction]);
    let b = ok(cli(&[
        "blame",
        "file.txt",
        "--line",
        "2",
        "--repo",
        s(p),
        "--sessions",
        s(&session),
        "--annotations",
        s(&annotations),
    ]));
    assert!(b["committedBy"].as_array().unwrap().is_empty());
}
#[test]
fn replay_tool_history_uses_effective_arguments_and_remaps_copy_ids() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("in.jsonl");
    let config = temp.path().join("provider.json");
    let out = temp.path().join("run.jsonl");
    replay_source(&input);
    let mut source = read(&input);
    let call = json!({"type":"tool_call","id":"old-call","callId":"old-tool","name":"shell","input":{"command":"original"}});
    let result = json!({"type":"tool_result","id":"old-result","callId":"old-tool","status":"completed","input":{"command":"effective"},"content":[{"type":"text","text":"recorded output"}]});
    source.splice(4..4, [call, result]);
    write(&input, &source);
    let response: Value =
        serde_json::from_str(include_str!("fixtures/openai-response.json")).unwrap();
    let (base, server) = serve("openai", response, 200);
    provider(&config, &base, "openai");
    ok(cli(&[
        "replay",
        s(&input),
        "--inference",
        "selected",
        "--provider-settings",
        s(&config),
        "--out",
        s(&out),
    ]));
    let request = server.join().unwrap();
    let call = request["messages"]
        .as_array()
        .unwrap()
        .iter()
        .find(|m| m.get("tool_calls").is_some())
        .unwrap();
    assert!(call["tool_calls"][0]["function"]["arguments"]
        .as_str()
        .unwrap()
        .contains("effective"));
    assert!(!call.to_string().contains("original"));
    let records = read(&out);
    let copy_call = records.iter().find(|r| r["type"] == "tool_call").unwrap();
    let copy_result = records.iter().find(|r| r["type"] == "tool_result").unwrap();
    assert_eq!(copy_call["callId"], copy_result["callId"]);
    assert_ne!(copy_call["callId"], "old-tool");
    assert_eq!(copy_call["copiedFrom"]["record"], "old-call");
    validate(&out);
}
#[test]
fn replay_masks_provider_key_in_output_and_records_malformed_responses() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("in.jsonl");
    let config = temp.path().join("provider.json");
    let out = temp.path().join("run.jsonl");
    replay_source(&input);
    let mut response: Value =
        serde_json::from_str(include_str!("fixtures/openai-response.json")).unwrap();
    response["choices"][0]["message"]["content"] = json!("echo synthetic-key");
    let (base, server) = serve("openai", response, 200);
    provider(&config, &base, "openai");
    ok(cli(&[
        "replay",
        s(&input),
        "--inference",
        "selected",
        "--provider-settings",
        s(&config),
        "--out",
        s(&out),
    ]));
    server.join().unwrap();
    assert!(!fs::read_to_string(&out).unwrap().contains("synthetic-key"));
    assert!(read(&out)[0]["missing"]
        .as_array()
        .unwrap()
        .contains(&json!("redacted_content")));
    validate(&out);
    let (base, server) = serve("openai", json!({"not":"a valid response"}), 200);
    provider(&config, &base, "openai");
    let bad = temp.path().join("bad-run.jsonl");
    let output = cli(&[
        "replay",
        s(&input),
        "--inference",
        "selected",
        "--provider-settings",
        s(&config),
        "--out",
        s(&bad),
    ]);
    assert_eq!(output.status.code(), Some(1));
    server.join().unwrap();
    validate(&bad);
    assert!(read(&bad)
        .iter()
        .any(|r| r["type"] == "inference" && r.get("error").is_some()));
}
#[test]
fn redact_unknown_data_exact_decimal_and_large_array_removal() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("in.jsonl");
    let out = temp.path().join("out.jsonl");
    let mut record=asr_core::jsonl::decode("{\"type\":\"com.example.record/new\",\"id\":\"opaque\",\"value\":1.234567890123456789e-99}").unwrap();
    record["values"] = json!((0..24).collect::<Vec<_>>());
    write(&input, &[header(), record]);
    ok(cli(&[
        "redact",
        s(&input),
        "--out",
        s(&out),
        "--remove",
        "/values/*",
    ]));
    let records = read(&out);
    assert_eq!(records[1]["value"].to_string(), "1.234567890123456789e-99");
    assert_eq!(records[1]["values"], json!([]));
    validate(&out);
}

#[test]
fn blame_joins_parent_and_child_links_and_respects_part_authorship() {
    let mut r = Repo::new();
    let p = r.temp.path();
    r.records[1]["author"] = json!("harness");
    r.records[1]["content"] = json!([{"type":"text","text":"injected"},{"type":"text","text":"human part","author":"human"},{"type":"text","text":"compaction","author":"human","origin":"compaction"}]);
    let b = r.blame(2);
    assert_eq!(
        b["editedBy"][0]["prompts"][0]["content"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
    assert_eq!(
        b["editedBy"][0]["prompts"][0]["content"][0]["text"],
        "human part"
    );
    r.records.push(json!({"type":"tool_call","id":"spawn","callId":"spawn-child","name":"delegate","subagent":{"session":"com.example.agent:child"}}));
    let parent = p.join("a-parent.jsonl");
    let child = p.join("z-child.jsonl");
    write(&parent, &r.records);
    let mut h = header();
    h["sessionId"] = json!("child");
    h["parent"] = json!({"session":"com.example.agent:synthetic","kind":"subagent"});
    write(&child, &[h]);
    let b = ok(cli(&[
        "blame",
        "file.txt",
        "--line",
        "2",
        "--repo",
        s(p),
        "--sessions",
        s(&parent),
        "--sessions",
        s(&child),
    ]));
    let link = &b["relationships"][0];
    assert_eq!(link["callId"], "spawn-child");
    assert_eq!(link["childAvailable"], true);
    assert_eq!(link["parentAvailable"], true);
}
#[test]
fn replay_refuses_ambiguous_history_and_world_readable_settings_before_sending() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("in.jsonl");
    let config = temp.path().join("provider.json");
    let out = temp.path().join("run.jsonl");
    replay_source(&input);
    let mut source = read(&input);
    source.splice(
        4..4,
        [
            json!({"type":"tool_call","id":"a","callId":"duplicate","name":"shell","input":{}}),
            json!({"type":"tool_call","id":"b","callId":"duplicate","name":"shell","input":{}}),
            json!({"type":"tool_result","id":"result","callId":"duplicate","status":"completed"}),
        ],
    );
    write(&input, &source);
    provider(&config, "http://127.0.0.1:1/v1", "openai");
    let output = cli(&[
        "replay",
        s(&input),
        "--inference",
        "selected",
        "--provider-settings",
        s(&config),
        "--out",
        s(&out),
    ]);
    assert_eq!(output.status.code(), Some(2));
    assert!(!out.exists());
    source.remove(5);
    source.remove(5);
    write(&input, &source);
    let other = temp.path().join("other.jsonl");
    let output = cli(&[
        "replay",
        s(&input),
        "--inference",
        "selected",
        "--provider-settings",
        s(&config),
        "--out",
        s(&other),
    ]);
    assert_eq!(output.status.code(), Some(2));
    assert!(!other.exists());
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&config, fs::Permissions::from_mode(0o644)).unwrap();
        let output = cli(&[
            "replay",
            s(&input),
            "--inference",
            "selected",
            "--provider-settings",
            s(&config),
            "--out",
            s(&other),
        ]);
        assert_eq!(output.status.code(), Some(2));
        assert!(!other.exists());
    }
}

#[test]
fn blame_uses_recorded_delegation_order_between_sessions() {
    let mut r = Repo::new();
    let p = r.temp.path();
    let mut child = r.records.clone();
    child[0]["sessionId"] = json!("child");
    child[0]["parent"] =
        json!({"session":"com.example.agent:synthetic","kind":"subagent","callId":"spawn-child"});
    r.records
        .push(json!({"type":"tool_call","id":"spawn","callId":"spawn-child","name":"delegate"}));
    r.records.push(json!({"type":"tool_result","id":"spawn-result","callId":"spawn-child","status":"completed"}));
    let parent = p.join("parent.jsonl");
    let file = p.join("child.jsonl");
    write(&parent, &r.records);
    write(&file, &child);
    let b = ok(cli(&[
        "blame",
        "file.txt",
        "--line",
        "2",
        "--repo",
        s(p),
        "--sessions",
        s(&parent),
        "--sessions",
        s(&file),
    ]));
    assert_eq!(b["editedBy"].as_array().unwrap().len(), 1);
    assert_eq!(b["editedBy"][0]["session"], "com.example.agent:child");
    assert_eq!(b["alternatives"].as_array().unwrap().len(), 1);
    let mut last = r.records[6].clone();
    last["id"] = json!("after-child");
    r.records.push(last);
    write(&parent, &r.records);
    let b = ok(cli(&[
        "blame",
        "file.txt",
        "--line",
        "2",
        "--repo",
        s(p),
        "--sessions",
        s(&parent),
        "--sessions",
        s(&file),
    ]));
    // The parent's later stale before-state exposes a reset of the child's
    // line. Neither old origin survives a verified replay.
    assert_eq!(b["editStatus"], "unknown");
    assert!(b["editedBy"].as_array().unwrap().is_empty());
}

#[test]
fn blame_matches_surviving_state_lines_and_content_hash_baselines() {
    let mut r = Repo::new();
    let p = r.temp.path();
    fs::write(p.join("file.txt"), "later context\nnew\n").unwrap();
    git(p, &["add", "file.txt"]);
    git(p, &["commit", "--amend", "-qm", "change"]);
    r.commit = git(p, &["rev-parse", "HEAD"]);
    r.records[7]["commit"] = json!(r.commit);
    assert_eq!(r.blame(2)["editStatus"], "unknown");
    let hash = format!(
        "{:x}",
        <sha2::Sha256 as sha2::Digest>::digest(b"context\nold\n")
    );
    r.records[6]["before"] = json!({"objectId":hash,"objectIdType":"sha256"});
    assert_eq!(r.blame(2)["editStatus"], "unknown");
    r.records[7]["actor"] = json!("human");
    assert_eq!(r.blame(2)["committedBy"][0]["credit"], "person");
}

#[test]
fn replay_preserves_unsafe_provider_counts_as_text_and_withholds_incomplete_totals() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("in.jsonl");
    let config = temp.path().join("provider.json");
    let out = temp.path().join("run.jsonl");
    replay_source(&input);
    let mut response: Value =
        serde_json::from_str(include_str!("fixtures/anthropic-response.json")).unwrap();
    response["usage"]["cache_read_input_tokens"] = json!(9007199254740993u64);
    let (base, server) = serve("anthropic", response, 200);
    provider(&config, &base, "anthropic");
    ok(cli(&[
        "replay",
        s(&input),
        "--inference",
        "selected",
        "--provider-settings",
        s(&config),
        "--out",
        s(&out),
    ]));
    server.join().unwrap();
    let records = read(&out);
    let inference = records.iter().find(|r| r["type"] == "inference").unwrap();
    assert!(inference["usage"].get("inputTokens").is_none());
    assert_eq!(
        inference["_meta"]["org.agentsessionrecord.tools"]["providerUsage"]
            ["/cache_read_input_tokens"],
        "9007199254740993"
    );
    assert!(records[0]["missing"]
        .as_array()
        .unwrap()
        .contains(&json!("usage")));
    validate(&out);
}

#[test]
fn blame_accepts_recorded_subdirectories_and_cwd_only_for_edit_candidates() {
    let mut r = Repo::new();
    let subdir = r.temp.path().join("nested");
    fs::create_dir(&subdir).unwrap();
    r.records[0]["cwd"] = json!(s(&subdir));
    r.records[0]["repos"][0]["path"] = json!(s(&subdir));
    r.records[6]["path"] = json!("../file.txt");
    let matched = r.blame(2);
    assert_eq!(matched["editStatus"], "matched");
    assert_eq!(matched["committedBy"].as_array().unwrap().len(), 1);
    r.records[0].as_object_mut().unwrap().remove("repos");
    let fallback = r.blame(2);
    assert_eq!(fallback["editStatus"], "matched");
    assert!(fallback["committedBy"].as_array().unwrap().is_empty());
    let outside = tempfile::tempdir().unwrap();
    r.records[0]["cwd"] = json!(s(outside.path()));
    r.records[6]["path"] = json!(s(&r.temp.path().join("file.txt")));
    assert_eq!(r.blame(2)["editStatus"], "unknown");
}

#[test]
fn blame_retains_repositories_added_after_an_unrelated_header() {
    let mut r = Repo::new();
    r.records[0]["repos"] = json!([{"path":"/unavailable/other"}]);
    r.records.push(
        json!({"type":"session_info","id":"repo-update","repos":[{"path":s(r.temp.path())}]}),
    );
    assert_eq!(r.blame(2)["editStatus"], "matched");
}

#[test]
fn blame_resolves_5000_sessions_with_constant_git_processes_under_five_seconds() {
    let r = Repo::new();
    let sessions = r.temp.path().join("sessions");
    fs::create_dir(&sessions).unwrap();
    for i in 0..5000 {
        let mut h = r.records[0].clone();
        h["sessionId"] = json!(format!("scale-{i}"));
        let mut records = vec![h, r.records[7].clone()];
        records.extend_from_slice(&r.records[1..7]);
        write(&sessions.join(format!("{i:04}.jsonl")), &records);
    }
    let trace = r.temp.path().join("git-trace.jsonl");
    let start = std::time::Instant::now();
    let output = Command::new(env!("CARGO_BIN_EXE_asr"))
        .args([
            "blame",
            "file.txt",
            "--line",
            "2",
            "--repo",
            s(r.temp.path()),
            "--sessions",
            s(&sessions),
        ])
        .env("GIT_TRACE2_EVENT", &trace)
        .output()
        .unwrap();
    let elapsed = start.elapsed();
    let report = ok(output);
    assert_eq!(report["editStatus"], "unresolved");
    assert_eq!(report["editedBy"].as_array().unwrap().len(), 5000);
    assert!(report["alternatives"].as_array().unwrap().is_empty());
    assert_eq!(report["sessions"].as_array().unwrap().len(), 5000);
    assert_eq!(report["committedBy"].as_array().unwrap().len(), 5000);
    let git_processes = read(&trace)
        .iter()
        .filter(|e| e["event"] == "start")
        .count();
    assert!(git_processes <= 12, "{git_processes} Git processes");
    eprintln!("5000 session lookup: {elapsed:?}, {git_processes} Git processes");
    assert!(
        elapsed < std::time::Duration::from_secs(5),
        "lookup took {elapsed:?}"
    );
}

#[test]
fn replay_codex_sample_excludes_the_unlinked_recorded_answer() {
    let temp = tempfile::tempdir().unwrap();
    let input = root().join("samples/codex/asr/session.jsonl");
    let source = read(&input);
    let selected = source
        .iter()
        .rev()
        .find(|r| r["type"] == "inference")
        .unwrap();
    let answer = source
        .iter()
        .rev()
        .find(|r| r["type"] == "message" && r["role"] == "assistant")
        .unwrap();
    let answer_text = answer["content"]
        .as_array()
        .unwrap()
        .iter()
        .find_map(|p| p["text"].as_str())
        .unwrap();
    let config = temp.path().join("provider.json");
    let out = temp.path().join("run.jsonl");
    let (base, server) = serve(
        "openai",
        json!({"id":"response","choices":[{"message":{"content":"new answer"}}]}),
        200,
    );
    provider(&config, &base, "openai");
    let report = ok(cli(&[
        "replay",
        s(&input),
        "--inference",
        selected["id"].as_str().unwrap(),
        "--provider-settings",
        s(&config),
        "--out",
        s(&out),
    ]));
    let request = server.join().unwrap();
    assert!(!request.to_string().contains(answer_text));
    assert_eq!(report["unlinkedOutputs"], true);
    let records = read(&out);
    assert!(records[0]["missing"]
        .as_array()
        .unwrap()
        .contains(&json!("replay_unlinked_outputs")));
    assert!(!records
        .iter()
        .any(|r| r["copiedFrom"]["record"] == answer["id"]));
    validate(&out);
}

#[test]
fn replay_unlinked_outputs_preserves_new_prompts_and_earlier_tool_results() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("source.jsonl");
    write(
        &input,
        &[
            header(),
            json!({"type":"message","id":"prior-prompt","role":"user","content":[{"type":"text","text":"first prompt"}]}),
            json!({"type":"tool_call","id":"prior-call","callId":"read","name":"read","input":{}}),
            json!({"type":"inference","id":"previous","model":{"requested":"test"}}),
            json!({"type":"tool_result","id":"prior-result","callId":"read","status":"completed","content":[{"type":"text","text":"earlier result"}]}),
            json!({"type":"message","id":"new-prompt","role":"user","content":[{"type":"text","text":"new prompt"}]}),
            json!({"type":"session_info","id":"tools","tools":[{"name":"read","inputSchema":{"type":"object"}}]}),
            json!({"type":"message","id":"answer","role":"assistant","content":[{"type":"text","text":"own answer"}]}),
            json!({"type":"inference","id":"selected","model":{"requested":"test"}}),
        ],
    );
    let config = temp.path().join("provider.json");
    let out = temp.path().join("run.jsonl");
    let (base, server) = serve(
        "openai",
        json!({"id":"response","choices":[{"message":{"content":"new answer"}}]}),
        200,
    );
    provider(&config, &base, "openai");
    ok(cli(&[
        "replay",
        s(&input),
        "--inference",
        "selected",
        "--provider-settings",
        s(&config),
        "--out",
        s(&out),
    ]));
    let request = server.join().unwrap();
    assert!(request.to_string().contains("earlier result"));
    assert!(request.to_string().contains("new prompt"));
    assert!(!request.to_string().contains("own answer"));
    assert_eq!(request["tools"][0]["function"]["name"], "read");
    validate(&out);
}

#[test]
fn redact_masks_payloads_without_changing_structural_fields() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("in.jsonl");
    let records = vec![
        header(),
        json!({"type":"message","id":"m","role":"user","author":"harness","origin":"injected","content":[
            {"type":"text","text":"private text"},
            {"type":"reasoning","text":"private thought","summary":["private summary"],"visibility":"summary"},
            {"type":"image","mimeType":"image/png","data":"cHJpdmF0ZQ=="},
            {"type":"resource","resource":{"uri":"file:///private.txt","mimeType":"text/plain","text":"private resource"}},
            {"type":"com.example.fixture/part","_meta":{"com.example.fixture":{"type":"private payload"}}}
        ]}),
        json!({"type":"tool_call","id":"c","callId":"call","name":"test","kind":"other","input":{"type":"private input","id":"private id"}}),
        json!({"type":"tool_result","id":"r","callId":"call","status":"completed","exec":{"exitCode":0,"stdout":"private output"}}),
    ];
    write(&input, &records);
    for (i, selector) in ["/content/*", "/content/*/type", "/*"].iter().enumerate() {
        let out = temp.path().join(format!("out-{i}.jsonl"));
        ok(cli(&[
            "redact",
            s(&input),
            "--out",
            s(&out),
            "--mask",
            selector,
        ]));
        let rows = read(&out);
        assert_eq!(rows[1]["type"], "message");
        assert_eq!(rows[1]["id"], "m");
        assert_eq!(rows[1]["role"], "user");
        assert_eq!(rows[1]["author"], "harness");
        assert_eq!(rows[1]["content"][0]["type"], "text");
        assert_eq!(rows[1]["content"][1]["visibility"], "summary");
        assert_eq!(rows[1]["content"][2]["mimeType"], "image/png");
        assert_eq!(rows[2]["callId"], "call");
        assert_eq!(rows[2]["kind"], "other");
        assert_eq!(rows[3]["status"], "completed");
        if i == 1 {
            assert_eq!(rows[1]["content"], records[1]["content"]);
        } else {
            assert_eq!(rows[1]["content"][0]["text"], "[REDACTED]");
            assert_eq!(rows[1]["content"][1]["summary"][0], "[REDACTED]");
            assert_eq!(
                rows[1]["content"][4]["_meta"]["com.example.fixture"]["type"],
                "[REDACTED]"
            );
            assert!(rows[0]["missing"]
                .as_array()
                .unwrap()
                .contains(&json!("redacted_content")));
        }
        if i == 2 {
            assert_eq!(rows[2]["input"]["type"], "[REDACTED]");
            assert_eq!(rows[2]["input"]["id"], "[REDACTED]");
        }
        validate(&out);
    }
}

#[test]
fn blame_refuses_ambiguous_replay_even_when_the_final_snippet_is_unique() {
    let mut r = Repo::new();
    r.records[6].as_object_mut().unwrap().remove("after");
    r.records[6]["before"] = json!({"text":"context\nold old\n"});
    r.records[6]["edits"] = json!([{"oldText":"old","newText":"new"}]);
    assert_eq!(r.blame(2)["editStatus"], "unknown");
    // The same guard applies when the original state came from an earlier Write.
    let mut write = r.records[6].clone();
    write["id"] = json!("earlier-write");
    write.as_object_mut().unwrap().remove("before");
    write.as_object_mut().unwrap().remove("edits");
    write["after"] = json!({"text":"context\nold old\n"});
    r.records[6].as_object_mut().unwrap().remove("before");
    r.records.insert(6, write);
    assert_eq!(r.blame(2)["editStatus"], "unknown");
}

#[test]
fn redact_edit_masks_follow_copies_across_records_and_vendor_payloads() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("input.jsonl");
    let out = temp.path().join("out.jsonl");
    let old = "    return a + b";
    let new = "    return a + b + c";
    let full = format!("def add(a, b, c):\n{new}\n");
    let native = json!({"originalFile":format!("def add(a, b, c):\n{old}\n"),"content":full,"oldString":old,"newString":new,"structuredPatch":[{"lines":[format!("-{old}"),format!("+{new}")]}]});
    write(
        &input,
        &[
            header(),
            json!({"type":"tool_call","id":"call","callId":"edit","name":"Edit","input":{"old_string":old,"new_string":new}}),
            json!({"type":"tool_result","id":"result","callId":"edit","status":"completed","content":[{"type":"text","text":native.to_string()}],"inputText":native.to_string(),"_meta":{"com.anthropic.claude-code":{"result":native}}}),
            json!({"type":"file_change","id":"change","path":"file.py","op":"modify","status":"applied","callId":"edit","edits":[{"oldText":old,"newText":new}],"_meta":{"com.anthropic.claude-code":{"result":native}}}),
            json!({"type":"com.openai.codex/event","id":"event","callId":"edit","payload":{"item":{"changes":{"file.py":{"unified_diff":format!("@@\n-{old}\n+{new}\n"),"content":full}}}},"_meta":{"com.openai.codex":{"native":{"payload":native}}}}),
        ],
    );
    let source = fs::read(&input).unwrap();
    ok(cli(&[
        "redact",
        s(&input),
        "--out",
        s(&out),
        "--mask",
        "/edits",
    ]));
    let text = fs::read_to_string(&out).unwrap();
    assert!(!text.contains(old));
    assert!(!text.contains(new));
    let records = read(&out);
    assert_eq!(records[3]["type"], "file_change");
    assert_eq!(records[3]["status"], "applied");
    assert_eq!(records[3]["path"], "file.py");
    assert_eq!(records[4]["type"], "com.openai.codex/event");
    assert!(records[1..].iter().all(|r| r["truncated"] == true));
    assert!(records[0]["missing"]
        .as_array()
        .unwrap()
        .contains(&json!("redacted_content")));
    assert_eq!(fs::read(&input).unwrap(), source);
    validate(&out);
}

#[test]
fn replay_response_scrubbing_declares_redacted_content() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("input.jsonl");
    replay_source(&input);
    let config = temp.path().join("provider.json");
    let out = temp.path().join("run.jsonl");
    let fake = format!("sk-{}", "z".repeat(32));
    let (base, server) = serve(
        "openai",
        json!({"id":"response","choices":[{"message":{"content":format!("synthetic {fake}")}}]}),
        200,
    );
    provider(&config, &base, "openai");
    ok(cli(&[
        "replay",
        s(&input),
        "--inference",
        "selected",
        "--provider-settings",
        s(&config),
        "--out",
        s(&out),
    ]));
    server.join().unwrap();
    let records = read(&out);
    let losses = records[0]["missing"].as_array().unwrap();
    assert!(losses.contains(&json!("redacted_content")));
    assert!(!losses.contains(&json!("redacted")));
    assert!(!fs::read_to_string(&out).unwrap().contains(&fake));
    validate(&out);
}

#[test]
fn redact_multiline_edits_masks_split_hunks_and_escaped_native_json() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("in.jsonl");
    let out = temp.path().join("out.jsonl");
    let old = "first = \"zero\"\nsecond = 0";
    let new = "first = \"one\"\nsecond = 1";
    let lines: Vec<_> = old
        .lines()
        .map(|s| format!("-{s}"))
        .chain(new.lines().map(|s| format!("+{s}")))
        .collect();
    let native = json!({"originalFile":format!("{old}\n"),"content":format!("{new}\n"),"structuredPatch":[{"lines":lines}],"renderedPatch":json!(lines).to_string()});
    write(
        &input,
        &[
            header(),
            json!({"type":"tool_call","id":"call","callId":"edit","name":"Edit","inputText":json!({"old_string":old,"new_string":new}).to_string()}),
            json!({"type":"tool_result","id":"result","callId":"edit","status":"completed","content":[{"type":"text","text":native.to_string()}]}),
            json!({"type":"file_change","id":"change","path":"file.py","op":"modify","status":"applied","callId":"edit","edits":[{"oldText":old,"newText":new}],"_meta":{"com.anthropic.claude-code":{"result":native}}}),
        ],
    );
    ok(cli(&[
        "redact",
        s(&input),
        "--out",
        s(&out),
        "--mask",
        "/edits",
    ]));
    let result = fs::read_to_string(&out).unwrap();
    for line in old.lines().chain(new.lines()) {
        let encoded = serde_json::to_string(line).unwrap();
        assert!(!result.contains(&encoded[1..encoded.len() - 1]));
    }
    assert!(read(&out)[1..].iter().all(|r| r["truncated"] == true));
    validate(&out);
}

#[test]
fn redact_copy_masks_have_a_minimum_length_and_stay_in_the_same_call() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("input.jsonl");
    let out = temp.path().join("out.jsonl");
    let long = "selected_value = 42";
    let selected = format!("{long}\n}}\n   \nshort\n!!!!!!!!!!!!");
    let unrelated = json!({"type":"message","id":"unrelated","role":"user","content":[{"type":"text","text":format!("use map.get(k) {{ }} here. {long}")}],"_meta":{"com.example.test":{"}":"}",long:long}}});
    let other = json!({"type":"tool_call","id":"other","callId":"other-call","name":"Edit","input":{"text":long}});
    write(
        &input,
        &[
            header(),
            json!({"type":"tool_call","id":"call","callId":"edit","name":"Edit","input":{"old_string":selected,"context":long,"brace":"}","word":"short","punctuation":"!!!!!!!!!!!!"}}),
            unrelated.clone(),
            other.clone(),
            json!({"type":"tool_result","id":"result","callId":"edit","status":"completed","content":[{"type":"text","text":format!("{long}\n}}\nshort\n!!!!!!!!!!!!")}]}),
            json!({"type":"file_change","id":"change","callId":"edit","path":"file.py","op":"modify","status":"applied","edits":[{"oldText":selected,"newText":"replacement_value = 43"}],"_meta":{"com.example.test":{"text":long,"}":"}","short-key":"short","!!!!!!!!!!!!":"punctuation"}}}),
            json!({"type":"com.example.test/event","id":"vendor","callId":"edit","payload":{"text":long}}),
        ],
    );
    ok(cli(&[
        "redact",
        s(&input),
        "--out",
        s(&out),
        "--mask",
        "/edits",
    ]));
    let records = read(&out);
    assert_eq!(records[2], unrelated);
    assert_eq!(records[3], other);
    assert_eq!(records[1]["input"]["old_string"], "[REDACTED]");
    assert_eq!(records[1]["input"]["context"], "[REDACTED]");
    assert_eq!(records[1]["input"]["brace"], "}");
    assert_eq!(records[1]["input"]["word"], "short");
    assert_eq!(records[1]["input"]["punctuation"], "!!!!!!!!!!!!");
    assert_eq!(
        records[4]["content"][0]["text"],
        "[REDACTED]\n}\nshort\n!!!!!!!!!!!!"
    );
    assert!(records[5]["_meta"]["com.example.test"].get("}").is_none());
    assert_eq!(
        records[5]["_meta"]["com.example.test"]["short-key"],
        "[REDACTED]"
    );
    assert_eq!(
        records[5]["_meta"]["com.example.test"]["!!!!!!!!!!!!"],
        Value::Null
    );
    assert_eq!(records[6]["payload"]["text"], "[REDACTED]");
    validate(&out);
}

#[test]
fn redact_short_selected_values_mask_every_copy_inside_the_record() {
    for short in ["}", "short", "   ", "!!!!!!!!!!!!"] {
        let temp = tempfile::tempdir().unwrap();
        let input = temp.path().join("input.jsonl");
        let out = temp.path().join("out.jsonl");
        write(
            &input,
            &[
                header(),
                json!({"type":"file_change","id":"change","path":"file.py","op":"modify","status":"applied","edits":[{"oldText":short,"newText":short}],"_meta":{"com.example.test":{"copy":short,short:"unrelated key"}}}),
            ],
        );
        ok(cli(&[
            "redact",
            s(&input),
            "--out",
            s(&out),
            "--mask",
            "/edits",
        ]));
        let records = read(&out);
        assert_eq!(records[1]["edits"][0]["oldText"], "[REDACTED]");
        assert_eq!(
            records[1]["_meta"]["com.example.test"]["copy"],
            "[REDACTED]"
        );
        assert!(records[1]["_meta"]["com.example.test"].get(short).is_none());
        validate(&out);
    }
}

#[test]
fn untimed_edits_need_commit_evidence_on_both_sides() {
    let mut r = Repo::new();
    r.records[6].as_object_mut().unwrap().remove("ts");
    assert_eq!(r.blame(2)["editStatus"], "unknown");
    r.records[6]["baseCommit"] = json!(git(r.temp.path(), &["rev-parse", "HEAD^"]));
    assert_eq!(r.blame(2)["editStatus"], "matched");
    r.records[7]["status"] = json!("failed");
    assert_eq!(r.blame(2)["editStatus"], "unknown");
    r.records[7]["status"] = json!("completed");
    r.records[6].as_object_mut().unwrap().remove("baseCommit");
    let parent = git(r.temp.path(), &["rev-parse", "HEAD^"]);
    r.records.insert(6, json!({"type":"vcs","id":"baseline","action":"commit","status":"completed","evidence":"observed","commit":parent}));
    assert_eq!(r.blame(2)["editStatus"], "matched");
    r.records[6]["copiedFrom"] = json!({"record":"source"});
    assert_eq!(r.blame(2)["editStatus"], "unknown");
}

#[test]
fn rewrite_timing_uses_the_original_commit_for_surviving_lines() {
    let mut r = Repo::new();
    git(r.temp.path(), &["commit", "--amend", "-qm", "rewritten"]);
    let successor = git(r.temp.path(), &["rev-parse", "HEAD"]);
    r.records.push(json!({"type":"vcs","id":"rewrite","action":"amend","status":"completed","evidence":"observed","commit":successor,"rewrites":[{"from":r.commit,"to":successor}]}));
    assert_eq!(r.blame(2)["editStatus"], "matched");
    r.records[6]["ts"] = json!("2026-01-01T00:15:00Z");
    assert_eq!(r.blame(2)["editStatus"], "unknown");
}

#[test]
fn ambiguous_call_ids_do_not_spread_masks_between_unrelated_calls() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("input.jsonl");
    let out = temp.path().join("out.jsonl");
    let text = "selected_value = 42";
    write(
        &input,
        &[
            header(),
            json!({"type":"tool_call","id":"call-one","callId":"reused","name":"Edit","input":{"text":text}}),
            json!({"type":"tool_call","id":"call-two","callId":"reused","name":"Read","input":{"text":text}}),
            json!({"type":"file_change","id":"change","callId":"reused","path":"file.py","op":"modify","status":"applied","edits":[{"oldText":text,"newText":text}],"_meta":{"com.example.test":{"copy":text}}}),
        ],
    );
    ok(cli(&[
        "redact",
        s(&input),
        "--out",
        s(&out),
        "--mask",
        "/edits",
    ]));
    let records = read(&out);
    assert_eq!(records[1]["input"]["text"], text);
    assert_eq!(records[2]["input"]["text"], text);
    assert_eq!(
        records[3]["_meta"]["com.example.test"]["copy"],
        "[REDACTED]"
    );
    validate(&out);
}

#[test]
fn ambiguous_predecessor_lines_cannot_use_a_rewrites_later_time_window() {
    let mut r = Repo::new();
    let amend = |contents: &str, at: &str| {
        fs::write(r.temp.path().join("file.txt"), contents).unwrap();
        git(r.temp.path(), &["add", "file.txt"]);
        let out = Command::new("git")
            .arg("-C")
            .arg(r.temp.path())
            .args([
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "--amend",
                "--no-edit",
                "-q",
            ])
            .env("GIT_CONFIG_NOSYSTEM", "1")
            .env("GIT_CONFIG_GLOBAL", "/dev/null")
            .env("GIT_COMMITTER_DATE", at)
            .env("GIT_COMMITTER_NAME", "Synthetic")
            .env("GIT_COMMITTER_EMAIL", "test@example.invalid")
            .output()
            .unwrap();
        assert!(out.status.success());
        git(r.temp.path(), &["rev-parse", "HEAD"])
    };
    let original = amend("context\nnew\nnew\n", "2026-01-01T00:10:00Z");
    let successor = amend("context\nnew\nkept\n", "2026-01-01T00:20:00Z");
    r.records[6]["before"] = json!({"text":"context\nfive\nkept\n"});
    r.records[6]["after"] = json!({"text":"context\nnew\nkept\n"});
    r.records[6]["ts"] = json!("2026-01-01T00:15:00Z");
    r.records[7]["commit"] = json!(original);
    r.records.push(json!({"type":"vcs","id":"rewrite","action":"amend","status":"completed","evidence":"observed","commit":successor,"rewrites":[{"from":original,"to":successor}]}));
    assert_eq!(r.blame(2)["editStatus"], "unknown");
}

#[test]
fn short_masks_cover_own_tool_inputs_results_patch_lines_and_escaped_copies() {
    for value in ["482913", "x", "}", " "] {
        let temp = tempfile::tempdir().unwrap();
        let input = temp.path().join("input.jsonl");
        let out = temp.path().join("out.jsonl");
        let untouched = json!({"type":"message","id":"unrelated","role":"user","content":[{"type":"text","text":value}]});
        write(
            &input,
            &[
                header(),
                json!({"type":"tool_call","id":"call","callId":"edit","name":"Edit","input":{"selected":value,"new_string":value},"_meta":{"com.example.test":{"originalFile":value,"structuredPatch":[format!("+{value}")],"escaped":serde_json::to_string(value).unwrap()}}}),
                json!({"type":"tool_result","id":"result","callId":"edit","status":"completed","content":[{"type":"text","text":value}]}),
                untouched.clone(),
            ],
        );
        ok(cli(&[
            "redact",
            s(&input),
            "--out",
            s(&out),
            "--mask",
            "/input/selected",
        ]));
        let records = read(&out);
        assert_eq!(records[1]["input"]["selected"], "[REDACTED]");
        assert_eq!(records[1]["input"]["new_string"], "[REDACTED]");
        assert_eq!(
            records[1]["_meta"]["com.example.test"]["originalFile"],
            "[REDACTED]"
        );
        assert_eq!(
            records[1]["_meta"]["com.example.test"]["structuredPatch"][0],
            "+[REDACTED]"
        );
        assert_eq!(records[2]["content"][0]["text"], value);
        assert_eq!(records[3], untouched);
        validate(&out);
    }
}
