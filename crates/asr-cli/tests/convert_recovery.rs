//! Conversion reports a failed session while publishing its valid neighbor.
use serde_json::{json, Value};
use std::{fs, process::Command};
#[test]
fn convert_reports_named_partial_failure_and_keeps_valid_output() {
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("native");
    fs::create_dir(&input).unwrap();
    for (name, time) in [("bad", "not-a-time"), ("good", "2026-01-01T00:00:00Z")] {
        fs::write(
            input.join(format!("{name}.jsonl")),
            format!(
                "{}\n",
                json!({"type":"session_meta","payload":{"id":name,"timestamp":time}})
            ),
        )
        .unwrap();
    }
    let out = temp.path().join("out");
    let result = Command::new(env!("CARGO_BIN_EXE_asr"))
        .args(["convert", "--agent", "codex"])
        .arg(input)
        .arg("--out")
        .arg(&out)
        .output()
        .unwrap();
    assert_eq!(result.status.code(), Some(1));
    let summary: Value = serde_json::from_slice(&result.stdout).unwrap();
    assert_eq!(summary["sessions"], 1);
    assert_eq!(
        summary["session_diagnostics"]["codex:bad"]["session_header_shape"],
        1
    );
    let files: Vec<_> = fs::read_dir(&out)
        .unwrap()
        .map(|e| e.unwrap().path())
        .collect();
    assert_eq!(files.len(), 1);
    let header: Value = serde_json::from_str(
        fs::read_to_string(&files[0])
            .unwrap()
            .lines()
            .next()
            .unwrap(),
    )
    .unwrap();
    assert_eq!(header["sessionId"], "good");
    let validator = Command::new("node")
        .arg(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/validator/bin/asr-validate.js"
        ))
        .arg("--summary")
        .arg(out)
        .output()
        .unwrap();
    assert!(
        validator.status.success(),
        "{}",
        String::from_utf8_lossy(&validator.stdout)
    );
}
