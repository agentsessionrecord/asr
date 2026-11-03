use super::*;
use clap::Args;
use regex::Regex;

#[derive(Args)]
pub struct Options {
    pub input: std::path::PathBuf,
    #[arg(long)]
    pub out: std::path::PathBuf,
    /// Remove fields with a JSON pointer. Use * for an array item or object field.
    #[arg(long)]
    pub remove: Vec<String>,
    /// Mask content strings and their copies in payloads and vendor metadata.
    /// Preserves ASR structural fields. Selectors use JSON pointers and *.
    #[arg(long)]
    pub mask: Vec<String>,
}

pub struct Scrubber {
    patterns: Vec<Regex>,
    known: Vec<String>,
}
impl Scrubber {
    pub fn new() -> Self {
        Self { known: Vec::new(), patterns: [
            r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{20,})\b",
            r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
            r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{8,}",
            r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}",
            r"(?s)-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----.*?(?:-----END (?:[A-Z0-9]+ )?PRIVATE KEY-----|$)",
            r#"(?i)(?:api[_-]?key|access[_-]?token|auth[_-]?token|refresh[_-]?token|secret[_-]?key|session[_-]?token|password)["']?\s*[=:]\s*["']?[^\s"',;}]+"#,
            r"(?i)https?://[^\s/@:]+:[^\s/@]+@",
        ].iter().map(|p| Regex::new(p).expect("constant pattern")).collect() }
    }
    pub fn string(&self, source: &str) -> String {
        let mut result = source.to_owned();
        for secret in &self.known {
            result = result.replace(secret, "[REDACTED]");
        }
        for pattern in &self.patterns {
            result = pattern.replace_all(&result, "[REDACTED]").into_owned();
        }
        result
    }
    pub fn add_secret(&mut self, value: Option<&str>) {
        if let Some(value) = value.filter(|s| !s.is_empty()) {
            self.known.push(value.to_owned());
        }
    }
    pub fn apply(&self, v: &mut Value) -> bool {
        let mut changed = false;
        match v {
            Value::String(s) => {
                let next = self.string(s);
                changed = *s != next;
                *s = next;
            }
            Value::Array(a) => {
                for v in a {
                    changed |= self.apply(v);
                }
            }
            Value::Object(o) => {
                let keys = o.keys().cloned().collect::<Vec<_>>();
                for key in keys {
                    if self.string(&key) != key {
                        o.remove(&key);
                        changed = true;
                    }
                }
                for (key, v) in o.iter_mut() {
                    let normalized = key.to_ascii_lowercase().replace(['_', '-'], "");
                    if [
                        "apikey",
                        "accesstoken",
                        "authtoken",
                        "authorization",
                        "refreshtoken",
                        "secretkey",
                        "sessiontoken",
                        "password",
                        "clientsecret",
                    ]
                    .contains(&normalized.as_str())
                        && !v.is_null()
                    {
                        if *v != "[REDACTED]" {
                            *v = json!("[REDACTED]");
                            changed = true;
                        }
                    } else {
                        changed |= self.apply(v);
                    }
                }
            }
            _ => {}
        }
        changed
    }
}

fn pointer(value: &str) -> Result<Vec<String>> {
    if !value.starts_with('/') {
        return Err("field selector must be a nonempty JSON pointer".into());
    }
    value[1..]
        .split('/')
        .map(|s| {
            let mut chars = s.chars();
            let mut result = String::new();
            while let Some(c) = chars.next() {
                if c == '~' {
                    result.push(match chars.next() {
                        Some('0') => '~',
                        Some('1') => '/',
                        _ => return Err("invalid JSON pointer escape".into()),
                    });
                } else {
                    result.push(c);
                }
            }
            Ok(result)
        })
        .collect()
}
fn content_path(path: &[String]) -> bool {
    let Some(root) = path.first().map(String::as_str) else {
        return false;
    };
    match root {
        // Opaque payloads have no ASR structural fields, even when named type or id.
        "input" | "native" | "_meta" => true,
        "inputText" | "patch" | "title" => path.len() == 1,
        "before" | "after" => path.get(1).is_some_and(|s| s == "text"),
        "edits" => path
            .get(2)
            .is_some_and(|s| matches!(s.as_str(), "oldText" | "newText")),
        "exec" => path
            .get(1)
            .is_some_and(|s| matches!(s.as_str(), "command" | "stdout" | "stderr" | "output")),
        "error" => path
            .get(1)
            .is_some_and(|s| matches!(s.as_str(), "message" | "code")),
        "content" => match path.get(2).map(String::as_str) {
            Some(
                "text" | "data" | "summary" | "description" | "name" | "title" | "uri" | "_meta",
            ) => true,
            Some("resource") => path
                .get(3)
                .is_some_and(|s| matches!(s.as_str(), "text" | "blob" | "uri")),
            _ => false,
        },
        _ => false,
    }
}
fn mask_selected(v: &mut Value, selector: &[String], path: &mut Vec<String>) -> bool {
    if path.len() <= selector.len() && path.iter().zip(selector).any(|(p, s)| s != "*" && s != p) {
        return false;
    }
    match v {
        Value::String(s)
            if path.len() >= selector.len() && content_path(path) && s != "[REDACTED]" =>
        {
            let binary = path.first().is_some_and(|p| p == "content")
                && (path.get(2).is_some_and(|p| p == "data")
                    || (path.get(2).is_some_and(|p| p == "resource")
                        && path.get(3).is_some_and(|p| p == "blob")));
            let replacement = if binary { "" } else { "[REDACTED]" };
            let changed = s != replacement;
            *s = replacement.into();
            changed
        }
        Value::Object(o) => {
            let mut changed = false;
            for (key, value) in o {
                path.push(key.clone());
                changed |= mask_selected(value, selector, path);
                path.pop();
            }
            changed
        }
        Value::Array(a) => {
            let mut changed = false;
            for (i, value) in a.iter_mut().enumerate() {
                path.push(i.to_string());
                changed |= mask_selected(value, selector, path);
                path.pop();
            }
            changed
        }
        _ => false,
    }
}
/// Collect selected values before mutation so copies in earlier records are
/// masked too, including escaped strings embedded in native JSON payloads.
fn collect_masks(v: &Value, selector: &[String], path: &mut Vec<String>, values: &mut Vec<String>) {
    if path.len() <= selector.len() && path.iter().zip(selector).any(|(p, s)| s != "*" && s != p) {
        return;
    }
    match v {
        Value::String(s)
            if path.len() >= selector.len()
                && content_path(path)
                && !s.is_empty()
                && s != "[REDACTED]" =>
        {
            // Native structuredPatch hunks and diff arrays split multi-line
            // replacements into separate strings. Cover raw and JSON-escaped
            // copies of substantial lines as well as the complete value.
            for part in std::iter::once(s.as_str()).chain(s.lines().filter(|line| !line.is_empty()))
            {
                // Copies inside the selected record have no length threshold.
                // Only propagation into other records needs substantial text.
                values.push(part.to_owned());
                let escaped = serde_json::to_string(part).expect("string encoding");
                values.push(escaped[1..escaped.len() - 1].to_owned());
            }
        }
        Value::Object(o) => {
            for (key, value) in o {
                path.push(key.clone());
                collect_masks(value, selector, path, values);
                path.pop();
            }
        }
        Value::Array(a) => {
            for (i, value) in a.iter().enumerate() {
                path.push(i.to_string());
                collect_masks(value, selector, path, values);
                path.pop();
            }
        }
        _ => {}
    }
}
fn mask_copies(v: &mut Value, values: &[String], path: &mut Vec<String>, vendor: bool) -> bool {
    let payload = content_path(path)
        || (vendor
            && path.first().is_some_and(|p| {
                ![
                    "type",
                    "id",
                    "ts",
                    "turnId",
                    "inferenceId",
                    "copiedFrom",
                    "truncated",
                ]
                .contains(&p.as_str())
            }));
    match v {
        Value::String(s) if payload => {
            let mut next = s.clone();
            for value in values {
                next = next
                    .split("[REDACTED]")
                    .map(|part| part.replace(value, "[REDACTED]"))
                    .collect::<Vec<_>>()
                    .join("[REDACTED]");
            }
            let changed = *s != next;
            *s = next;
            changed
        }
        Value::Object(o) => {
            let mut changed = false;
            if payload {
                let keys: Vec<_> = o
                    .keys()
                    .filter(|k| {
                        values.iter().any(|v| {
                            *k == v
                                || (v.trim().chars().count() >= 8
                                    && v.chars().any(char::is_alphanumeric)
                                    && k.contains(v))
                        })
                    })
                    .cloned()
                    .collect();
                for key in keys {
                    o.remove(&key);
                    changed = true;
                }
            }
            for (key, value) in o {
                path.push(key.clone());
                changed |= mask_copies(value, values, path, vendor);
                path.pop();
            }
            changed
        }
        Value::Array(a) => {
            let mut changed = false;
            for (i, value) in a.iter_mut().enumerate() {
                path.push(i.to_string());
                changed |= mask_copies(value, values, path, vendor);
                path.pop();
            }
            changed
        }
        _ => false,
    }
}
fn select(v: &mut Value, path: &[String], remove: bool) -> bool {
    if path.is_empty() {
        return false;
    }
    let key = &path[0];
    let keys: Vec<String> = match v {
        Value::Object(o) => o
            .keys()
            .filter(|k| key == "*" || *k == key)
            .cloned()
            .collect(),
        Value::Array(a) => (0..a.len())
            .map(|i| i.to_string())
            .filter(|k| key == "*" || k == key)
            .collect(),
        _ => return false,
    };
    let mut changed = false;
    for key in keys.into_iter().rev() {
        if remove && path.len() == 1 {
            match v {
                Value::Object(o) => {
                    changed |= o.remove(&key).is_some();
                }
                Value::Array(a) => {
                    a.remove(key.parse::<usize>().unwrap());
                    changed = true;
                }
                _ => {}
            }
        } else if let Some(next) = match v {
            Value::Array(a) => a.get_mut(key.parse::<usize>().unwrap()),
            _ => v.get_mut(&key),
        } {
            changed |= select(next, &path[1..], remove);
        }
    }
    changed
}

pub fn run(options: Options) -> Result<Value> {
    let stream = Stream::load(&options.input)?;
    let remove = options
        .remove
        .iter()
        .map(|s| pointer(s))
        .collect::<Result<Vec<_>>>()?;
    let masks = options
        .mask
        .iter()
        .map(|s| pointer(s))
        .collect::<Result<Vec<_>>>()?;
    let mut records = stream.records;
    let inherited = records
        .iter()
        .filter_map(|r| r["missing"].as_array())
        .flatten()
        .filter_map(Value::as_str)
        .map(str::to_owned)
        .collect::<std::collections::BTreeSet<_>>();
    let scrubber = Scrubber::new();
    let mut call_counts = std::collections::BTreeMap::<String, usize>::new();
    for r in records.iter().filter(|r| r["type"] == "tool_call") {
        if let Some(call) = text(r, "callId") {
            *call_counts.entry(call.to_owned()).or_default() += 1;
        }
    }
    let mut record_values = Vec::new();
    let mut call_values = std::collections::BTreeMap::<String, Vec<String>>::new();
    for r in &records {
        let mut values = Vec::new();
        for selector in &masks {
            collect_masks(r, selector, &mut Vec::new(), &mut values);
        }
        if let Some(call) = text(r, "callId").filter(|call| call_counts.get(*call) == Some(&1)) {
            call_values.entry(call.to_owned()).or_default().extend(
                values
                    .iter()
                    .filter(|part| {
                        part.trim().chars().count() >= 8 && part.chars().any(char::is_alphanumeric)
                    })
                    .cloned(),
            );
        }
        record_values.push(values);
    }
    let mut changed = 0;
    for (r, mut values) in records.iter_mut().zip(record_values) {
        if let Some(related) = text(r, "callId").and_then(|call| call_values.get(call)) {
            values.extend(related.iter().cloned());
        }
        // Longest first prevents a shorter selected value from hiding a longer one.
        values.sort_by(|a, b| b.len().cmp(&a.len()).then_with(|| a.cmp(b)));
        values.dedup();
        let mut touched = scrubber.apply(r);
        for p in &remove {
            touched |= select(r, p, true);
        }
        for p in &masks {
            touched |= mask_selected(r, p, &mut Vec::new());
        }
        let vendor = text(r, "type").is_some_and(|t| t.contains('/'));
        touched |= mask_copies(r, &values, &mut Vec::new(), vendor);
        if touched {
            r["truncated"] = json!(true);
            changed += 1;
        }
    }
    records[0]["producer"] = producer("agent-session-jsonl");
    records[0]["derivedFrom"] = json!({"sha256":stream.sha256});
    let mut losses = inherited;
    if changed > 0 {
        losses.insert("redacted_content".into());
    }
    if !stream.warnings.is_empty() {
        losses.insert("history".into());
    }
    records[0]["missing"] = json!(losses);
    let mut result = write_session(&options.out, &records)?;
    result["redactedRecords"] = json!(changed);
    result["sourceWarnings"] = json!(stream.warnings);
    Ok(result)
}
