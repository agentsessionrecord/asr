//! Check every native/ASR worked example currently published in the agent notes.
use asr_convert::{convert, Agent, Options};
use rusqlite::{params, Connection};
use serde_json::Value;
use std::{
    fs,
    path::{Path, PathBuf},
};
fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}
fn block(document: &str, fence: &str) -> Vec<Value> {
    document
        .split_once(fence)
        .unwrap()
        .1
        .split_once("```")
        .unwrap()
        .0
        .lines()
        .filter(|s| !s.trim().is_empty())
        .map(|s| serde_json::from_str(s).unwrap())
        .collect()
}
fn subset(expected: &Value, actual: &Value) -> bool {
    match expected {
        Value::Object(o) => o
            .iter()
            .filter(|(k, _)| !matches!(k.as_str(), "id" | "inferenceId" | "approvalId"))
            .all(|(k, v)| actual.get(k).is_some_and(|a| subset(v, a))),
        Value::Array(a) => actual
            .as_array()
            .is_some_and(|b| a.len() == b.len() && a.iter().zip(b).all(|(a, b)| subset(a, b))),
        _ => expected == actual,
    }
}
#[test]
fn all_published_worked_examples_preserve_their_documented_core_facts_and_links() {
    for agent in [
        Agent::ClaudeCode,
        Agent::Codex,
        Agent::GeminiCli,
        Agent::OpenCode,
        Agent::OpenClaw,
    ] {
        let document =
            fs::read_to_string(root().join(format!("agents/{}.md", agent.name()))).unwrap();
        let example = document.split_once("## Worked example").unwrap().1;
        let native = block(example, "```jsonl native\n");
        let expected = block(example, "```jsonl\n");
        let temp = tempfile::tempdir().unwrap();
        let source = temp.path().join(if agent == Agent::OpenCode {
            "native.db"
        } else {
            "native.jsonl"
        });
        if agent == Agent::OpenCode {
            let db = Connection::open(&source).unwrap();
            db.execute_batch("CREATE TABLE session(id TEXT); CREATE TABLE message(id TEXT,session_id TEXT,data TEXT); CREATE TABLE part(id TEXT,message_id TEXT,session_id TEXT,data TEXT);").unwrap();
            db.execute(
                "INSERT INTO session VALUES(?1)",
                [native[0]["id"].as_str().unwrap()],
            )
            .unwrap();
            db.execute(
                "INSERT INTO message VALUES(?1,?2,?3)",
                params![
                    native[1]["id"].as_str(),
                    native[1]["session_id"].as_str(),
                    native[1]["data"].to_string()
                ],
            )
            .unwrap();
            db.execute(
                "INSERT INTO part VALUES(?1,?2,?3,?4)",
                params![
                    native[2]["id"].as_str(),
                    native[2]["message_id"].as_str(),
                    native[2]["session_id"].as_str(),
                    native[2]["data"].to_string()
                ],
            )
            .unwrap();
        } else {
            fs::write(
                &source,
                native.iter().map(|v| format!("{v}\n")).collect::<String>(),
            )
            .unwrap();
        }
        let out = temp.path().join("out");
        let summary = convert(&Options::new(agent, source, out.clone())).unwrap();
        assert_eq!(summary.sessions, 1, "{}", agent.name());
        assert_eq!(
            summary.diagnostics.len(),
            0,
            "{}: {:?}",
            agent.name(),
            summary.diagnostics
        );
        let validation = std::process::Command::new("node")
            .arg(root().join("tools/validator/bin/asr-validate.js"))
            .arg("--summary")
            .arg(&out)
            .output()
            .unwrap();
        assert!(
            validation.status.success(),
            "{}: {}",
            agent.name(),
            String::from_utf8_lossy(&validation.stdout)
        );
        let output = fs::read_dir(out).unwrap().next().unwrap().unwrap().path();
        let rows: Vec<Value> = fs::read_to_string(output)
            .unwrap()
            .lines()
            .map(|s| serde_json::from_str(s).unwrap())
            .collect();
        assert_eq!(rows[0]["sessionId"], expected[0]["sessionId"]);
        let mut pairs = Vec::new();
        for expected in expected.iter().skip(1) {
            let matches: Vec<_> = rows.iter().filter(|r| subset(expected, r)).collect();
            assert_eq!(
                matches.len(),
                1,
                "{}: expected {} in {}",
                agent.name(),
                expected,
                serde_json::to_string(&rows).unwrap()
            );
            pairs.push((expected, matches[0]));
        }
        for (expected, actual) in &pairs {
            for field in ["inferenceId", "approvalId"] {
                if let Some(link) = expected[field].as_str() {
                    let target = pairs.iter().find(|(e, _)| e["id"] == link).unwrap().1;
                    assert_eq!(actual[field], target["id"], "{} {field}", agent.name());
                }
            }
        }
    }
}
