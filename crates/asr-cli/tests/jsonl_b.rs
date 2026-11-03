use std::{path::Path, process::Command};
#[test]
fn every_jsonl_b_agent_is_registered_and_accepted_by_convert() {
    let binary = env!("CARGO_BIN_EXE_asr");
    let listing = Command::new(binary).arg("agents").output().unwrap();
    assert!(listing.status.success());
    let listing = String::from_utf8(listing.stdout).unwrap();
    for agent in [
        "antigravity",
        "tabnine",
        "qoder",
        "droid",
        "copilot-cli",
        "qwen-code",
        "grok-build",
        "pi",
        "kimi-code",
        "deepseek-harness",
        "junie",
        "openclaw",
    ] {
        assert!(listing.lines().any(|l| l.split('\t').next() == Some(agent)));
        let out = tempfile::tempdir().unwrap();
        let input = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../asr-convert/tests/fixtures/jsonl-b")
            .join(agent);
        let output = Command::new(binary)
            .args(["convert", "--agent", agent])
            .arg(input)
            .arg("--out")
            .arg(out.path())
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{agent}: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        let summary: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
        assert_eq!(
            summary["sessions"],
            if agent == "copilot-cli" { 2 } else { 1 }
        );
    }
}
