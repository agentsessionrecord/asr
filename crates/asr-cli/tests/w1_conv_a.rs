use std::{path::Path, process::Command};
#[test]
fn five_registered_agents_convert_through_cli() {
    let bin = env!("CARGO_BIN_EXE_asr");
    let agents = Command::new(bin).arg("agents").output().unwrap();
    assert!(agents.status.success());
    for agent in ["cursor", "gemini-cli", "mistral-vibe", "mux", "fx"] {
        assert!(String::from_utf8_lossy(&agents.stdout)
            .lines()
            .any(|s| s.starts_with(&format!("{agent}\t"))));
        let temp = tempfile::tempdir().unwrap();
        let out = temp.path().join("out");
        let result = Command::new(bin)
            .args(["convert", "--agent", agent])
            .arg(
                Path::new(env!("CARGO_MANIFEST_DIR"))
                    .join("../asr-convert/tests/fixtures/w1-conv-a")
                    .join(agent),
            )
            .arg("--out")
            .arg(&out)
            .output()
            .unwrap();
        assert!(
            result.status.success(),
            "{agent}: {}",
            String::from_utf8_lossy(&result.stderr)
        );
        assert!(Command::new(bin)
            .args(["validate", "--summary"])
            .arg(out)
            .output()
            .unwrap()
            .status
            .success());
    }
}
