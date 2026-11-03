//! MiMoCode uses the verified OpenCode-family storage mapping.
use crate::{common::Context, spool::Spool, Result};
use serde_json::Value;
pub(crate) fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    crate::opencode::convert(s, c, v)
}
