//! The public CLI converts recorded edits and attributes a committed line in Git.
use serde_json::Value;
use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
};
fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}
fn git(repo: &Path, args: &[&str]) -> String {
    let baseline = args
        .iter()
        .any(|a| a.contains("baseline") || *a == "Baseline");
    let at = if baseline {
        "2026-01-01T00:00:00Z"
    } else {
        "2026-01-01T00:10:00Z"
    };
    let result = Command::new("git")
        .args([
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.fsmonitor=false",
        ])
        .arg("-C")
        .arg(repo)
        .args(args)
        .env("GIT_AUTHOR_DATE", at)
        .env("GIT_COMMITTER_DATE", at)
        .env("GIT_CONFIG_NOSYSTEM", "1")
        .env("GIT_CONFIG_GLOBAL", "/dev/null")
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    String::from_utf8(result.stdout).unwrap().trim().into()
}
fn timed_native(source: &str) -> String {
    source
        .lines()
        .map(|line| {
            let mut record: Value = serde_json::from_str(line).unwrap();
            record["timestamp"] = serde_json::json!("2026-01-01T00:05:00Z");
            // This positive citation test supplies an observed baseline. Bare
            // partial replacements are covered by conservative regressions.
            if record["toolUseResult"]["filePath"]
                .as_str()
                .is_some_and(|p| p.ends_with("/file.txt"))
            {
                record["toolUseResult"]["originalFile"] = serde_json::json!("unchanged\nold\n");
            }
            format!("{record}\n")
        })
        .collect()
}
fn cli(args: &[&str]) -> Value {
    let result = Command::new(env!("CARGO_BIN_EXE_asr"))
        .args(args)
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "{} {}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
    serde_json::from_slice(&result.stdout).unwrap()
}
#[test]
fn converted_claude_and_codex_edits_resolve_to_their_sessions_prompts_and_models() {
    for agent in ["claude-code", "codex"] {
        let temp = tempfile::tempdir().unwrap();
        let repo = temp.path().join("repo");
        fs::create_dir(&repo).unwrap();
        git(&repo, &["init", "--initial-branch=main"]);
        git(&repo, &["config", "user.name", "Synthetic Test"]);
        git(&repo, &["config", "user.email", "test@example.com"]);
        fs::write(repo.join("file.txt"), "unchanged\nold\n").unwrap();
        git(&repo, &["add", "file.txt"]);
        git(&repo, &["commit", "-m", "Synthetic baseline"]);
        let head = git(&repo, &["rev-parse", "HEAD"]);
        let native = fs::read_to_string(
            root().join(format!("samples/{agent}/synthetic-success/native.jsonl")),
        )
        .unwrap()
        .replace("/work/app", repo.to_str().unwrap())
        .replace(&"a".repeat(40), &head);
        let source = temp.path().join("native.jsonl");
        let native = if agent == "claude-code" {
            native
                .replace("\"old\\n\"", "\"old\"")
                .replace("\"new\\n\"", "\"new\"")
        } else {
            native
        };
        let native = timed_native(&native);
        fs::write(&source, &native).unwrap();
        fs::write(repo.join("file.txt"), "unchanged\nnew\n").unwrap();
        git(&repo, &["diff", "--check"]);
        let out = temp.path().join("out");
        let summary = cli(&[
            "convert",
            "--agent",
            agent,
            source.to_str().unwrap(),
            "--out",
            out.to_str().unwrap(),
        ]);
        assert_eq!(summary["sessions"], 1);
        assert_eq!(summary["diagnostics"], serde_json::json!({}));
        let exported = fs::read_dir(&out).unwrap().next().unwrap().unwrap().path();
        let expected =
            fs::read_to_string(root().join(format!("samples/{agent}/synthetic-success/asr.jsonl")))
                .unwrap()
                .replace("/work/app", repo.to_str().unwrap())
                .replace(&"a".repeat(40), &head);
        let expected = if agent == "claude-code" {
            expected
                .replace("\"old\\n\"", "\"old\"")
                .replace("\"new\\n\"", "\"new\"")
        } else {
            expected
        };
        let normalize = |source: &str| {
            source
                .lines()
                .map(|line| {
                    let mut record: Value = serde_json::from_str(line).unwrap();
                    // Derived IDs can incorporate the substituted scratch file path.
                    record.as_object_mut().unwrap().remove("id");
                    record.as_object_mut().unwrap().remove("ts");
                    if record
                        .pointer("/_meta/com.anthropic.claude-code/result/filePath")
                        .and_then(Value::as_str)
                        .is_some_and(|p| p.ends_with("/file.txt"))
                    {
                        record["_meta"]["com.anthropic.claude-code"]["result"]["originalFile"] =
                            serde_json::json!("unchanged\nold\n");
                        record["before"] = serde_json::json!({"text":"unchanged\nold\n"});
                    }
                    if let Some(native) = record
                        .pointer_mut("/_meta/com.openai.codex/native")
                        .and_then(Value::as_object_mut)
                    {
                        native.remove("timestamp");
                    }
                    record
                })
                .collect::<Vec<_>>()
        };
        assert_eq!(
            normalize(&fs::read_to_string(exported).unwrap()),
            normalize(&expected)
        );
        let validator = Command::new("node")
            .arg(root().join("tools/validator/bin/asr-validate.js"))
            .args(["--json", "--summary"])
            .arg(&out)
            .output()
            .unwrap();
        assert!(
            validator.status.success(),
            "{}",
            String::from_utf8_lossy(&validator.stdout)
        );
        let validation: Value = serde_json::from_slice(&validator.stdout).unwrap();
        assert_eq!(validation["errors"], 0);
        git(&repo, &["add", "file.txt"]);
        git(&repo, &["commit", "-m", "Synthetic recorded edit"]);
        let result = cli(&[
            "blame",
            "file.txt",
            "--line",
            "2",
            "--repo",
            repo.to_str().unwrap(),
            "--sessions",
            out.to_str().unwrap(),
        ]);
        let session = format!(
            "{agent}:synthetic-{}-edit",
            if agent == "claude-code" {
                "claude"
            } else {
                "codex"
            }
        );
        assert_eq!(result["editStatus"], "matched");
        assert_eq!(result["editedBy"][0]["session"], session);
        assert!(result["editedBy"][0]["reference"]
            .as_str()
            .unwrap()
            .starts_with(&format!("{session}#")));
        assert_eq!(
            result["editedBy"][0]["prompts"][0]["content"][0]["text"],
            "Change the second line to new and check the edit."
        );
        assert_eq!(result["editedBy"][0]["model"]["kind"], "served");
        assert_eq!(
            result["editedBy"][0]["model"]["value"],
            "example-served-model"
        );
        assert!(result["committedBy"].as_array().unwrap().is_empty());
        println!(
            "{}",
            serde_json::json!({"agent":agent,"editStatus":result["editStatus"],"reference":result["editedBy"][0]["reference"],"promptCount":result["editedBy"][0]["prompts"].as_array().unwrap().len(),"modelKind":result["editedBy"][0]["model"]["kind"],"validationErrors":validation["errors"],"validationWarnings":validation["warnings"]})
        );
        assert_eq!(fs::read_to_string(&source).unwrap(), native);
    }
}

#[test]
fn claude_replays_partial_multiline_edits_and_shifts_written_lines_before_one_commit() {
    let temp = tempfile::tempdir().unwrap();
    let repo = temp.path().join("repo");
    fs::create_dir(&repo).unwrap();
    git(&repo, &["init", "--initial-branch=main"]);
    git(&repo, &["config", "user.name", "Synthetic Test"]);
    git(&repo, &["config", "user.email", "test@example.com"]);
    fs::write(
        repo.join("calc.py"),
        "def add(a, b):\n    return a + b\n\n# untouched context\n",
    )
    .unwrap();
    git(&repo, &["add", "."]);
    git(&repo, &["commit", "-m", "Baseline"]);
    let native =
        include_str!("native/claude-edits.jsonl").replace("/work/app", repo.to_str().unwrap());
    let source = temp.path().join("native.jsonl");
    fs::write(&source, timed_native(&native)).unwrap();
    let out = temp.path().join("out");
    let summary = cli(&[
        "convert",
        "--agent",
        "claude-code",
        source.to_str().unwrap(),
        "--out",
        out.to_str().unwrap(),
    ]);
    assert_eq!(summary["sessions"], 1);
    fs::write(
        repo.join("calc.py"),
        "def add(a, b, c=0):\n    return a + b + c\n\n# untouched context\n",
    )
    .unwrap();
    fs::write(
        repo.join("created.py"),
        "# header\nvalue = 2\n\n# retained write line\nprint(value + 1)\n",
    )
    .unwrap();
    git(&repo, &["add", "."]);
    git(&repo, &["commit", "-m", "Recorded changes"]);
    for (file, line, call) in [
        ("calc.py", "1", "edit-1"),
        ("calc.py", "2", "edit-1"),
        ("created.py", "1", "shift-1"),
        ("created.py", "2", "shift-1"),
        ("created.py", "4", "write-1"),
        ("created.py", "5", "tail-1"),
    ] {
        let result = cli(&[
            "blame",
            file,
            "--line",
            line,
            "--repo",
            repo.to_str().unwrap(),
            "--sessions",
            out.to_str().unwrap(),
        ]);
        assert_eq!(result["editStatus"], "matched", "{file}:{line}");
        assert!(result["editedBy"][0]["call"]
            .as_str()
            .unwrap()
            .ends_with(&format!("#{call}")));
        assert_eq!(
            result["editedBy"][0]["model"]["value"],
            "example-served-model"
        );
        assert_eq!(
            result["editedBy"][0]["prompts"].as_array().unwrap().len(),
            1
        );
    }
    let result = cli(&[
        "blame",
        "calc.py",
        "--line",
        "4",
        "--repo",
        repo.to_str().unwrap(),
        "--sessions",
        out.to_str().unwrap(),
    ]);
    assert_eq!(result["editStatus"], "unknown");
    let validation = Command::new("node")
        .arg(root().join("tools/validator/bin/asr-validate.js"))
        .arg("--summary")
        .arg(out)
        .output()
        .unwrap();
    assert!(validation.status.success());
}
