//! Explicit credentials and secret answers are removed before projection (ASR-060).
use crate::{spool::Spool, Result};
use serde_json::Value;

fn credential_key(key: &str) -> bool {
    let mut normalized = String::new();
    let mut previous_lower = false;
    for ch in key.chars() {
        if ch.is_ascii_uppercase() && previous_lower {
            normalized.push('_');
        }
        previous_lower = ch.is_ascii_lowercase() || ch.is_ascii_digit();
        normalized.push(match ch {
            '-' | '.' | ' ' => '_',
            _ => ch.to_ascii_lowercase(),
        });
    }
    normalized == "token"
        || [
            "password",
            "passwd",
            "api_key",
            "access_token",
            "refresh_token",
            "auth_token",
            "session_token",
            "secret_key",
            "secret_access_key",
            "authorization",
            "credential",
            "credentials",
            "client_secret",
            "private_key",
            "cookie",
            "cookies",
            "set_cookie",
            "secret",
            "secrets",
        ]
        .iter()
        .any(|name| normalized == *name || normalized.ends_with(&format!("_{name}")))
}

pub fn questions(spool: &Spool, v: &Value) -> Result<()> {
    match v {
        Value::Object(o) => {
            if o.get("secret") == Some(&Value::Bool(true))
                || o.get("isSecret") == Some(&Value::Bool(true))
            {
                if let Some(id) = o.get("requestId").and_then(Value::as_str) {
                    spool
                        .db
                        .execute("INSERT OR IGNORE INTO secret_questions VALUES(?1)", [id])?;
                }
            }
            if let Some(qs) = o.get("questions").and_then(Value::as_array) {
                for (i, q) in qs.iter().enumerate() {
                    if q["secret"] == true || q["isSecret"] == true {
                        let qid = q["id"]
                            .as_str()
                            .map(str::to_owned)
                            .unwrap_or_else(|| i.to_string());
                        spool
                            .db
                            .execute("INSERT OR IGNORE INTO secret_questions VALUES(?1)", [qid])?;
                        if let Some(text) = q["question"].as_str() {
                            spool.db.execute(
                                "INSERT OR IGNORE INTO secret_questions VALUES(?1)",
                                [text],
                            )?;
                        }
                    }
                }
            }
            for (key, x) in o {
                // Explicit credential fields establish a secret. Schema
                // definitions and boolean secret markers are not values.
                if credential_key(key) && x.is_string() {
                    strings(spool, x)?;
                }
                questions(spool, &Value::String(key.clone()))?;
                questions(spool, x)?;
            }
        }
        Value::Array(a) => {
            for x in a {
                questions(spool, x)?;
            }
        }
        Value::String(s) => {
            // Recognizable credential syntax supplies evidence even inside recorded commands.
            static TOKENS: std::sync::OnceLock<Vec<regex::Regex>> = std::sync::OnceLock::new();
            let patterns = TOKENS.get_or_init(|| [
                r"(sk-[A-Za-z0-9_-]{12,}|sess-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|xox[baprs]-[A-Za-z0-9-]{12,}|(?:AKIA|ASIA)[A-Z0-9]{16}|AIza[A-Za-z0-9_-]{30,}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)",
                r"(?i)\bBearer\s+([A-Za-z0-9._~+/=-]+)",
                r"(?i)\bBasic\s+([A-Za-z0-9+/]{16,}={0,2})",
                r"(?s)(-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|$))",
                r#"(?i)\b(?:password|passwd|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|auth[_ -]?token|session[_ -]?token|authorization|client[_ -]?secret|secret|cookie|token)["']?\s*[:=]\s*"([^"\r\n]+)""#,
                r#"(?i)\b(?:password|passwd|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|auth[_ -]?token|session[_ -]?token|authorization|client[_ -]?secret|secret|cookie|token)["']?\s*[:=]\s*'([^'\r\n]+)'"#,
                r#"(?i)\b(?:password|passwd|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|auth[_ -]?token|session[_ -]?token|authorization|client[_ -]?secret|secret|cookie|token)["']?\s*[:=]\s*([^\s,;}"']+)"#,
                r#"://([^/\s@]+)@"#,
                r#"(?i)[?&](?:api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|session[_-]?token|client[_-]?secret|password|secret|token)=([^&#\s"']+)"#,
            ].iter().map(|pattern| regex::Regex::new(pattern).expect("credential pattern")).collect());
            for regex in patterns {
                for found in regex.captures_iter(s) {
                    strings(spool, &Value::String(found[1].into()))?;
                }
            }
            if s.trim_start().starts_with('{') || s.trim_start().starts_with('[') {
                if let Ok(parsed) = serde_json::from_str::<Value>(s) {
                    questions(spool, &parsed)?;
                }
            }
        }
        _ => {}
    }
    Ok(())
}
fn strings(spool: &Spool, v: &Value) -> Result<()> {
    match v {
        Value::String(s) if !s.is_empty() && !s.starts_with("[secret answer redacted]") => {
            let exists: bool = spool.db.query_row(
                "SELECT EXISTS(SELECT 1 FROM secrets WHERE value=?1)",
                [s],
                |r| r.get(0),
            )?;
            if !exists {
                let bytes = spool.secret_bytes.get().saturating_add(s.len());
                if bytes > spool.limit {
                    return Err(crate::Error::Invalid(
                        "in-memory secret matching limit exceeded".into(),
                    ));
                }
                spool.db.execute("INSERT INTO secrets VALUES(?1)", [s])?;
                spool.secret_bytes.set(bytes);
                spool.secret_matcher.borrow_mut().take();
            }
        }
        Value::Array(a) => {
            for x in a {
                strings(spool, x)?;
            }
        }
        Value::Object(o) => {
            for x in o.values() {
                strings(spool, x)?;
            }
        }
        _ => {}
    }
    Ok(())
}
pub fn answers(spool: &Spool, v: &Value) -> Result<()> {
    match v {
        Value::Object(o) => {
            if let Some(id) = o.get("requestId").and_then(Value::as_str) {
                let secret: bool = spool.db.query_row(
                    "SELECT EXISTS(SELECT 1 FROM secret_questions WHERE id=?1)",
                    [id],
                    |r| r.get(0),
                )?;
                if secret {
                    for key in ["answer", "response"] {
                        if let Some(value) = o.get(key) {
                            strings(spool, value)?;
                        }
                    }
                }
            }
            if let Some(a) = o.get("answers").and_then(Value::as_object) {
                for (key, value) in a {
                    let secret: bool = spool.db.query_row(
                        "SELECT EXISTS(SELECT 1 FROM secret_questions WHERE id=?1)",
                        [key],
                        |r| r.get(0),
                    )?;
                    if secret {
                        strings(spool, value)?;
                    }
                }
            }
            for x in o.values() {
                answers(spool, x)?;
            }
        }
        Value::Array(a) => {
            for x in a {
                answers(spool, x)?;
            }
        }
        Value::String(s) if s.trim_start().starts_with('{') || s.trim_start().starts_with('[') => {
            if let Ok(parsed) = serde_json::from_str::<Value>(s) {
                answers(spool, &parsed)?;
            }
        }
        _ => {}
    }
    Ok(())
}
pub fn sanitize(spool: &Spool, v: &mut Value) -> Result<bool> {
    if !spool.has_secrets {
        return Ok(false);
    }
    let mut changed = false;
    match v {
        Value::String(s) => {
            if s.trim_start().starts_with('{') || s.trim_start().starts_with('[') {
                // Redact JSON string tokens without parsing/re-serializing numbers:
                // an unrelated secret answer must not round an unsafe native integer.
                let bytes = s.as_bytes();
                let (mut i, mut copied) = (0, 0);
                let mut output = String::new();
                while i < bytes.len() {
                    if bytes[i] != b'"' {
                        i += 1;
                        continue;
                    }
                    let start = i;
                    i += 1;
                    while i < bytes.len() && bytes[i] != b'"' {
                        if bytes[i] == b'\\' {
                            i += 1;
                        }
                        i += 1;
                    }
                    if i >= bytes.len() {
                        break;
                    }
                    i += 1;
                    if let Ok(text) = serde_json::from_str::<String>(&s[start..i]) {
                        let mut token = Value::String(text.clone());
                        sanitize(spool, &mut token)?;
                        if token.as_str() != Some(text.as_str()) {
                            output.push_str(&s[copied..start]);
                            output.push_str(&serde_json::to_string(&token)?);
                            copied = i;
                        }
                    }
                }
                if copied > 0 {
                    output.push_str(&s[copied..]);
                    *s = output;
                    return Ok(true);
                }
            }
            for value in matching_secrets(spool, s)? {
                *s = s.replace(&value, "[secret answer redacted]");
                changed = true;
            }
        }
        Value::Array(a) => {
            for x in a {
                changed |= sanitize(spool, x)?;
            }
        }
        Value::Object(o) => {
            let original = std::mem::take(o);
            for (key, mut x) in original {
                let mut clean_key = Value::String(key);
                changed |= sanitize(spool, &mut clean_key)?;
                changed |= sanitize(spool, &mut x)?;
                let key = clean_key.as_str().unwrap();
                let mut unique = key.to_owned();
                let mut suffix = 1;
                while o.contains_key(&unique) {
                    unique = format!("{key} [{suffix}]");
                    suffix += 1;
                }
                o.insert(unique, x);
            }
        }
        _ => {}
    }
    Ok(changed)
}

pub(crate) struct Matcher {
    long: aho_corasick::AhoCorasick,
    long_ids: Vec<usize>,
    short: std::collections::HashMap<String, usize>,
    values: Vec<String>,
}

fn matching_secrets(spool: &Spool, text: &str) -> Result<Vec<String>> {
    if spool.secret_matcher.borrow().is_none() {
        // Keep the original longest-first SQL order, including ties. Short
        // values match only the whole string. SQLite supplies Unicode lengths.
        let mut statement = spool
            .db
            .prepare("SELECT value,length(value) FROM secrets ORDER BY rowid")?;
        let mut values = statement
            .query_map([], |row| {
                Ok((row.get::<_, String>(0)?, row.get::<_, usize>(1)?))
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        // Sort in memory so SQLite cannot spill secret values to a temp file.
        values.sort_by_key(|v| std::cmp::Reverse(v.1));
        let long_ids: Vec<_> = values
            .iter()
            .enumerate()
            .filter(|(_, v)| v.1 >= 8)
            .map(|(id, _)| id)
            .collect();
        let long = aho_corasick::AhoCorasick::new(long_ids.iter().map(|id| &values[*id].0))
            .map_err(|_| crate::Error::Invalid("secret matcher initialization failed".into()))?;
        let short = values
            .iter()
            .enumerate()
            .filter(|(_, v)| v.1 < 8)
            .map(|(id, v)| (v.0.clone(), id))
            .collect();
        *spool.secret_matcher.borrow_mut() = Some(Matcher {
            long,
            long_ids,
            short,
            values: values.into_iter().map(|v| v.0).collect(),
        });
    }
    let cached = spool.secret_matcher.borrow();
    let matcher = cached.as_ref().unwrap();
    let mut ids = std::collections::BTreeSet::new();
    if let Some(id) = matcher.short.get(text) {
        ids.insert(*id);
    }
    for found in matcher.long.find_overlapping_iter(text) {
        ids.insert(matcher.long_ids[found.pattern().as_usize()]);
    }
    Ok(ids
        .into_iter()
        .map(|id| matcher.values[id].clone())
        .collect())
}

pub fn prepare(spool: &mut Spool) -> Result<()> {
    use rusqlite::OptionalExtension;
    let questions: bool =
        spool
            .db
            .query_row("SELECT EXISTS(SELECT 1 FROM secret_questions)", [], |r| {
                r.get(0)
            })?;
    if questions {
        let mut pos = 0u64;
        loop {
            let row:Option<(u64,String)>=spool.db.query_row("SELECT pos,value FROM native WHERE pos>?1 AND (instr(value,'answer')>0 OR instr(value,'response')>0) ORDER BY pos LIMIT 1",[pos],|r|Ok((r.get(0)?,r.get(1)?))).optional()?;
            let Some((next, raw)) = row else {
                break;
            };
            pos = next;
            answers(spool, &serde_json::from_str(&raw)?)?;
        }
    }
    spool.has_secrets = spool
        .db
        .query_row("SELECT EXISTS(SELECT 1 FROM secrets)", [], |r| r.get(0))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn named_and_embedded_credentials_are_removed_including_object_keys() {
        let temporary = tempfile::tempdir().unwrap();
        let mut spool = Spool::new(temporary.path(), 1024 * 1024).unwrap();
        let mut value = json!({
            "sessionToken": "synthetic-session-value",
            "clientSecret": "synthetic-client-value",
            "cookies": "synthetic-cookie-value",
            "text": "synthetic-session-value synthetic-client-value synthetic-cookie-value",
            "auth": "Basic c3ludGhldGljLW9ubHk=",
            "url": "https://synthetic-user:synthetic-pass@example.invalid/?token=synthetic-query-value",
            "serialized": "{\"password\":\"synthetic-json-value\",\"echo\":\"synthetic-json-value\",\"n\":9007199254740993}",
            "command": "password='synthetic-quoted value'",
            "ordinary": "Follow basic instructions.",
            "keys": {"synthetic-session-value": 1, "synthetic-client-value": 2},
            "token_count": 10
        });
        questions(&spool, &value).unwrap();
        prepare(&mut spool).unwrap();
        assert!(sanitize(&spool, &mut value).unwrap());
        let raw = value.to_string();
        for secret in [
            "synthetic-session-value",
            "synthetic-client-value",
            "synthetic-cookie-value",
            "c3ludGhldGljLW9ubHk=",
            "synthetic-user:synthetic-pass",
            "synthetic-query-value",
            "synthetic-json-value",
            "synthetic-quoted value",
        ] {
            assert!(!raw.contains(secret));
        }
        assert_eq!(value["keys"].as_object().unwrap().len(), 2);
        assert_eq!(value["token_count"], 10);
        assert_eq!(value["ordinary"], "Follow basic instructions.");
        assert!(value["serialized"]
            .as_str()
            .unwrap()
            .contains("9007199254740993"));
    }

    #[test]
    fn matcher_matches_sql_and_refreshes_after_new_secrets() {
        let temporary = tempfile::tempdir().unwrap();
        let mut spool = Spool::new(temporary.path(), 1024 * 1024).unwrap();
        let known = [
            "a",
            "synthetic-long-value",
            "overlapping-value",
            "value",
            "雪雪雪雪雪雪雪雪",
            "abcdefgh",
            "bcdefghi",
            "abc\0defghijk",
        ];
        for secret in known {
            strings(&spool, &json!(secret)).unwrap();
        }
        spool.has_secrets = true;
        for secret in known {
            for text in [
                secret.to_owned(),
                format!("prefix {secret} suffix"),
                "unrelated".into(),
                "abcdefghi".into(),
            ] {
                let mut statement = spool.db.prepare(
                    "SELECT value FROM secrets WHERE value=?1 OR (length(value)>=8 AND instr(?1,value)>0) ORDER BY length(value) DESC",
                ).unwrap();
                let expected = statement
                    .query_map([&text], |row| row.get::<_, String>(0))
                    .unwrap()
                    .collect::<std::result::Result<Vec<_>, _>>()
                    .unwrap();
                assert_eq!(matching_secrets(&spool, &text).unwrap(), expected);
            }
        }
        strings(&spool, &json!("new-synthetic-secret")).unwrap();
        let mut value = json!({"text":"prefix new-synthetic-secret suffix","json":r#"{"answer":"synthetic-long-\u0076alue"}"#});
        assert!(sanitize(&spool, &mut value).unwrap());
        assert_eq!(value["text"], "prefix [secret answer redacted] suffix");
        assert!(!value["json"].as_str().unwrap().contains("long"));
    }
}

/// Remove opaque provider state while preserving staging markers until projection.
pub(crate) fn scrub_opaque(v: &mut Value, remove_markers: bool) -> bool {
    let mut changed = false;
    match v {
        Value::Object(o) => {
            let encrypted = o.get("type").and_then(Value::as_str) == Some("redacted_thinking")
                || o.get("visibility").and_then(Value::as_str) == Some("encrypted")
                || o.get("type").and_then(Value::as_str) == Some("thinking")
                    && o.get("redacted") == Some(&Value::Bool(true));
            if encrypted {
                for key in ["text", "thinking", "summary", "data", "content"] {
                    changed |= o.remove(key).is_some();
                }
            }
            o.retain(|key, _| {
                let keep = !(matches!(
                    key.as_str(),
                    "signature"
                        | "thoughtSignature"
                        | "textSignature"
                        | "thinkingSignature"
                        | "thought_signature"
                        | "OpenAIResponsesReasoning"
                        | "encrypted"
                        | "encrypted_content"
                        | "encrypted_function_args"
                        | "replayState"
                        | "opaque"
                        | "reasoning_details"
                        | "codex_reasoning_items"
                        | "provider_state"
                ) || remove_markers && key == "_asrRedacted");
                changed |= !keep;
                keep
            });
            for child in o.values_mut() {
                changed |= scrub_opaque(child, remove_markers);
            }
        }
        Value::Array(a) => {
            for child in a {
                changed |= scrub_opaque(child, remove_markers);
            }
        }
        _ => {}
    }
    changed
}

#[cfg(test)]
mod opaque_tests {
    use super::scrub_opaque;
    use serde_json::json;

    #[test]
    fn shared_scrubber_removes_every_source_profiles_opaque_state() {
        let mut value = json!({
            "_asrRedacted": true,
            "content": [
                {"type":"thinking", "redacted":true, "thinking":"synthetic", "signature":"synthetic"},
                {"type":"reasoning", "visibility":"encrypted", "text":"synthetic", "data":"synthetic"},
                {"type":"text", "text":"keep exact text  ", "textSignature":"synthetic"}
            ],
            "nested": {"thought_signature":"synthetic", "OpenAIResponsesReasoning":"synthetic", "thoughtSignature":"synthetic", "encrypted_function_args":"synthetic", "replayState":{}, "provider_state":{}, "reasoning_details":[], "codex_reasoning_items":[], "opaque":"synthetic", "encrypted_content":"synthetic", "encrypted":"synthetic", "thinkingSignature":"synthetic"}
        });
        assert!(scrub_opaque(&mut value, false));
        assert_eq!(
            value,
            json!({
                "_asrRedacted": true,
                "content": [
                    {"type":"thinking", "redacted":true},
                    {"type":"reasoning", "visibility":"encrypted"},
                    {"type":"text", "text":"keep exact text  "}
                ],
                "nested": {}
            })
        );
        assert!(!scrub_opaque(&mut value, false));
        assert!(scrub_opaque(&mut value, true));
        assert!(value.get("_asrRedacted").is_none());
        assert_eq!(value["content"][2]["text"], "keep exact text  ");
    }
}
