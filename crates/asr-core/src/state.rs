use serde_json::{json, Value};
use std::collections::BTreeSet;

#[derive(Debug, Default, Clone)]
pub struct SessionState {
    pub facts: Value,
    pub missing: BTreeSet<String>,
}
impl SessionState {
    pub fn apply(&mut self, record: &Value) {
        if !self.facts.is_object() {
            self.facts = json!({});
        }
        if let Some(losses) = record["missing"].as_array() {
            self.missing
                .extend(losses.iter().filter_map(Value::as_str).map(str::to_owned));
        }
        if record["type"] != "session" && record["type"] != "session_info" {
            return;
        }
        for key in ["title", "endedAt", "usage", "cost", "tools"] {
            if let Some(v) = record.get(key) {
                self.facts[key] = v.clone();
            }
        }
        if let Some(repos) = record["repos"].as_array() {
            if !self.facts["repos"].is_array() {
                self.facts["repos"] = json!([]);
            }
            for repo in repos {
                let existing = self.facts["repos"].as_array_mut().unwrap();
                if !existing.contains(repo) {
                    existing.push(repo.clone());
                }
            }
        }
        if let Some(settings) = record["agentSettings"].as_object() {
            if !self.facts["agentSettings"].is_object() {
                self.facts["agentSettings"] = json!({});
            }
            let dest = self.facts["agentSettings"].as_object_mut().unwrap();
            if ["mode", "approval", "sandbox"]
                .iter()
                .any(|k| settings.get(*k).is_some_and(|v| dest.get(*k) != Some(v)))
                && !settings.contains_key("asks")
            {
                dest.remove("asks");
            }
            for (key, value) in settings {
                if value.is_null() {
                    dest.remove(key);
                } else if key == "modelSettings" {
                    let model = dest.entry(key).or_insert_with(|| json!({}));
                    if !model.is_object() {
                        *model = json!({});
                    }
                    for (field, value) in value.as_object().into_iter().flatten() {
                        if value.is_null() {
                            model.as_object_mut().unwrap().remove(field);
                        } else {
                            model[field] = value.clone();
                        }
                    }
                } else {
                    dest.insert(key.clone(), value.clone());
                }
            }
        }
    }
}

/// Results override call arguments only after the caller establishes unique pairing.
pub fn effective_input<'a>(
    call: &'a Value,
    result: Option<&'a Value>,
) -> Option<(&'static str, &'a Value)> {
    for value in result.into_iter().chain(std::iter::once(call)) {
        for field in ["input", "inputText"] {
            if let Some(input) = value.get(field) {
                return Some((field, input));
            }
        }
    }
    None
}
