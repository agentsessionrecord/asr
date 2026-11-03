//! Roo Code task stores share the API history contract.
use crate::{common::Context, documents as d, spool::Spool, Agent, Result, Summary};
use serde_json::Value;
use std::path::Path;
pub fn stage(s: &mut Spool, path: &Path, v: &Value, summary: &mut Summary) -> Result<()> {
    crate::cline::stage_task(s, Agent::RooCode, path, v, summary)
}
pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if v["kind"] == "ui" {
        crate::cline::convert(s, c, v)
    } else {
        d::project(s, c, v)
    }
}
