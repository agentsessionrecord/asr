use super::helpers::*;
use crate::{
    common::{self, Context},
    spool::Spool,
    Result,
};
use serde_json::{json, Value};
pub fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if v["kind"] == "UserPromptEvent" {
        return message(s, c, "user", &v["prompt"], None, None, None, None);
    }
    if v["kind"] != "SessionA2uxEvent" {
        return Ok(());
    }
    let e = &v["event"]["agentEvent"];
    if !matches!(
        e["kind"].as_str(),
        Some(
            "TerminalBlockUpdatedEvent"
                | "ToolBlockUpdatedEvent"
                | "ViewFilesBlockUpdatedEvent"
                | "FileChangesBlockUpdatedEvent"
        )
    ) {
        return Ok(());
    }
    let Some(step) = string(&e["stepId"]) else {
        return Ok(());
    };
    let id = asr_core::identity::derive_id(&[&c.session, "step", step]);
    let args = e.get("command").map(|cmd| json!({"command":cmd}));
    call(
        s,
        c,
        Some(&id),
        None,
        args.as_ref(),
        false,
        None,
        Some(&format!("step-call:{step}")),
        None,
    )?;
    if e.get("details").is_some() || e.get("status").is_some() {
        let mut r = json!({"type":"tool_result","callId":id,"status":match e["status"].as_str(){Some("COMPLETED")=>"completed",Some("FAILED")=>"failed",Some("CANCELLED")=>"cancelled",_=>"unknown"}});
        meta(c, &mut r, "displayDetails", &e["details"]);
        if let Some(cmd) = e["command"].as_str() {
            r["exec"]["command"] = json!(cmd);
        }
        if let Some(code) = e["exitCode"].as_i64() {
            r["exec"]["exitCode"] = json!(code);
        }
        if let Some(n) = count(&e["durationMs"]) {
            r["durationMs"] = json!(n);
        }
        c.result(s, r)?;
    }
    if e["kind"] == "FileChangesBlockUpdatedEvent" {
        for (i, change) in e["changes"].as_array().into_iter().flatten().enumerate() {
            let before = change["beforeRelativePath"].as_str();
            let after = change["afterRelativePath"].as_str();
            let Some(path) = after.or(before) else {
                continue;
            };
            let op = match (before, after) {
                (None, Some(_)) => "add",
                (Some(_), None) => "delete",
                (Some(a), Some(b)) if a != b => "move",
                _ => "modify",
            };
            let mut r = json!({"type":"file_change","callId":id,"path":common::path(path,c.cwd.as_deref()),"op":op,"status":"unknown"});
            if op == "move" {
                r["oldPath"] = json!(common::path(before.unwrap(), c.cwd.as_deref()));
            }
            for side in ["before", "after"] {
                if let Some(text) = change[format!("{side}Content")]["text"].as_str() {
                    r[side] = json!({"text":text});
                }
            }
            c.emit(s, r, None, Some(&format!("step-change:{step}:{i}")))?;
        }
    }
    Ok(())
}
