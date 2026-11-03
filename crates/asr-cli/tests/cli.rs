use std::{path::Path, process::Command};
#[test]
fn agents_and_validation_exit_codes() {
    let bin = env!("CARGO_BIN_EXE_asr");
    let output = Command::new(bin).arg("agents").output().unwrap();
    assert!(output.status.success());
    let listed = String::from_utf8(output.stdout).unwrap();
    assert_eq!(listed.lines().count(), asr_convert::Agent::ALL.len());
    for agent in asr_convert::Agent::ALL {
        assert!(listed
            .lines()
            .any(|line| line.split_whitespace().next() == Some(agent.name())));
    }
    let repo = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let good = Command::new(bin)
        .args(["validate", "--summary"])
        .arg(repo.join("samples/codex/asr"))
        .current_dir(&repo)
        .output()
        .unwrap();
    assert!(good.status.success(), "Workspace integration tests require Node and the validator dependencies. Run pnpm --filter @agent-session/validate install --frozen-lockfile first. Validator output: {} {}", String::from_utf8_lossy(&good.stdout), String::from_utf8_lossy(&good.stderr));
    let temp = tempfile::tempdir().unwrap();
    let file = temp.path().join("invalid.jsonl");
    std::fs::write(&file, "{}\n").unwrap();
    let bad = Command::new(bin)
        .arg("validate")
        .arg(file)
        .current_dir(repo)
        .output()
        .unwrap();
    assert_eq!(bad.status.code(), Some(1));
    let missing = Command::new(bin)
        .arg("validate")
        .arg("missing.jsonl")
        .env("ASR_REPO_ROOT", temp.path())
        .output()
        .unwrap();
    assert_eq!(missing.status.code(), Some(2));
}

#[test]
fn agents_exits_cleanly_when_its_reader_closes_the_pipe() {
    use std::process::Stdio;
    let mut child = Command::new(env!("CARGO_BIN_EXE_asr"))
        .arg("agents")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    drop(child.stdout.take());
    let output = child.wait_with_output().unwrap();
    assert!(output.status.success());
    assert!(output.stderr.is_empty());
}
