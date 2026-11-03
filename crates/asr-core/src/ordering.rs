use serde_json::Value;

/// A stable source position, independent of event timestamps.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct Position {
    pub observation: u64,
    pub slot: u64,
}

/// Fold facts at the completing observation. Missing fields retain earlier facts.
/// Model-facing content replaces display content. Text deltas use concatenation.
pub fn fold_completed(previous: &mut Value, update: &Value) {
    for (key, value) in update.as_object().into_iter().flatten() {
        if key == "status" && value == "unknown" && previous.get(key).is_some() {
            continue;
        }
        if matches!(key.as_str(), "exec" | "_meta") && value.is_object() {
            if !previous[key].is_object() {
                previous[key] = serde_json::json!({});
            }
            fold_completed(&mut previous[key], value);
        } else {
            previous[key] = value.clone();
        }
    }
    // Completion without a timestamp cannot inherit an earlier observation's time.
    if update.get("ts").is_none() {
        previous.as_object_mut().unwrap().remove("ts");
    }
}

pub fn append_delta(text: &mut String, delta: &str) {
    text.push_str(delta);
}
