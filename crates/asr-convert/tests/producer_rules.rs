//! Source guards for approval producers across the repository.
use std::{fs, path::Path};
#[test]
fn approval_producers_do_not_assign_literal_subjects() {
    let pattern = regex::Regex::new(r#"(?:\[\s*["']subject["']\s*\]\s*=\s*(?:json!\()?|(?:["']subject["']|\bsubject)\s*:)\s*["']([^"'\n]+)["']"#).unwrap();
    fn scan(path: &Path, pattern: &regex::Regex) {
        for entry in fs::read_dir(path).unwrap() {
            let entry = entry.unwrap();
            let kind = entry.file_type().unwrap();
            let path = entry.path();
            if kind.is_symlink() {
                continue;
            }
            if kind.is_dir() {
                let name = entry.file_name();
                if !matches!(
                    name.to_str(),
                    Some(
                        "target"
                            | "node_modules"
                            | "test"
                            | "tests"
                            | "fixtures"
                            | "__tests__"
                            | ".venv"
                            | "__pycache__"
                    )
                ) {
                    scan(&path, pattern);
                }
            } else if path
                .extension()
                .and_then(|s| s.to_str())
                .is_some_and(|s| matches!(s, "rs" | "py" | "ts" | "js" | "mjs" | "go"))
            {
                let source = fs::read_to_string(&path).unwrap();
                for found in pattern.captures_iter(&source) {
                    // A column-name map does not assign a subject to an approval.
                    assert_eq!(
                        &found[1],
                        "subject",
                        "literal subject in {}",
                        path.display()
                    );
                }
            }
        }
    }
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    for directory in [
        "crates",
        "plugins",
        "recorders",
        "packages/writer",
        "python",
        "importers",
        "exporters",
    ] {
        scan(&root.join(directory), &pattern);
    }
    for source in [
        "r[\"subject\"] = json!(\"placeholder\");",
        "{ subject: \"placeholder\" }",
        "{'subject': 'placeholder'}",
    ] {
        assert!(pattern.is_match(source));
    }
}
