//! Native JSONL adapters. All source evidence passes through the shared privacy filter.
mod antigravity;
mod copilot;
mod deepseek;
mod droid;
mod grok;
mod helpers;
mod junie;
mod kimi;
mod openclaw;
mod pi;
mod qoder;
mod qwen;
pub(crate) mod source;
mod tabnine;
use crate::{common::Context, spool::Spool, Agent, Result};
use serde_json::Value;

pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    let mut safe = v.clone();
    crate::privacy::scrub_opaque(&mut safe, false);
    let v = &safe;
    helpers::position(c, v);
    if v["type"] == "_gap" {
        return c.emit(s, v["record"].clone(), None, None);
    }
    if let Some(copy) = v.get("_asrCopy") {
        c.source["copiedFrom"] = copy.clone();
    }
    // Keep unsupported and supplementary evidence without claiming core semantics.
    c.vendor(s, v)?;
    match c.agent {
        Agent::Antigravity => antigravity::convert(s, c, v),
        Agent::Tabnine => tabnine::convert(s, c, v),
        Agent::Qoder => qoder::convert(s, c, v),
        Agent::Droid => droid::convert(s, c, v),
        Agent::CopilotCli => copilot::convert(s, c, v),
        Agent::QwenCode => qwen::convert(s, c, v),
        Agent::GrokBuild => grok::convert(s, c, v),
        Agent::Pi => pi::convert(s, c, v),
        Agent::KimiCode => kimi::convert(s, c, v),
        Agent::DeepSeekHarness => deepseek::convert(s, c, v),
        Agent::Junie => junie::convert(s, c, v),
        Agent::OpenClaw => openclaw::convert(s, c, v),
        _ => unreachable!(),
    }
}
