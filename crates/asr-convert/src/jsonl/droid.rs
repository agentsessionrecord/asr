use super::helpers::*;
use crate::{common::Context, spool::Spool, Result};
use serde_json::Value;
pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    match v["type"].as_str() {
        Some("message") => {
            let m = v.get("message").unwrap_or(v);
            if let Some(role) = m["role"].as_str().or_else(|| v["role"].as_str()) {
                blocks(
                    s,
                    c,
                    v,
                    role,
                    m.get("content")
                        .or_else(|| v.get("content"))
                        .unwrap_or(&Value::Null),
                )?;
            }
        }
        Some("compaction_state") => compaction(s, c, v.get("summary"), true)?,
        _ => {}
    }
    Ok(())
}
