//! OpenClaw window identities, sequenced transcripts and mutable node snapshots.
use crate::{
    common::{self, Context},
    spool::Spool,
    sqlite as q, Agent, Result,
};
use rusqlite::Connection;
use serde_json::{json, Value};
use std::path::Path;
fn native_header(s: &Spool, id: &str, n: &Value) -> Result<()> {
    q::update_header(s, id, |h| {
        crate::repository::capture(h, Agent::OpenClaw, n);
        if let Some(cwd) = n["cwd"].as_str().filter(|p| common::absolute(p)) {
            h["cwd"] = json!(cwd);
        }
        if let Some(start) = q::time(&n["timestamp"], true) {
            h["startedAt"] = json!(start);
        }
    })
}
pub(crate) fn stage(db: &Connection, s: &Spool, id: &str, row: &Value, path: &Path) -> Result<()> {
    let node = if let Some(key) = row["session_key"].as_str() {
        let n = q::one(db, "session_nodes", "session_key", key, s.limit)?;
        q::parse(&n["entry_json"])
            .filter(|n| n["sessionId"] == id)
            .unwrap_or(Value::Null)
    } else {
        Value::Null
    };
    let ancestor = row["previous_session_id"]
        .as_str()
        .or_else(|| node["forkSource"]["sessionId"].as_str());
    q::update_header(s, id, |h| {
        if let Some(start) = q::time(&row["started_at"], true) {
            h["startedAt"] = json!(start);
        }
        if let Some(end) = q::time(&row["ended_at"], true) {
            h["endedAt"] = json!(end);
        }
        if let Some(ancestor) = ancestor {
            let kind = if row["reason"] == "fork" || node["forkSource"]["sessionId"].is_string() {
                Some("fork")
            } else if matches!(
                row["reason"].as_str(),
                Some(
                    "reset"
                        | "rollover"
                        | "rewind"
                        | "switch"
                        | "recovery"
                        | "compaction"
                        | "daily"
                        | "idle"
                )
            ) {
                Some("continues")
            } else {
                None
            };
            if let Some(kind) = kind {
                h["parent"] =
                    json!({"kind":kind,"session":q::reference(h,Agent::OpenClaw,ancestor)});
            }
        }
        let actor = node
            .get("delegatedBy")
            .filter(|v| !v.is_null())
            .unwrap_or(&node["createdActor"]);
        if actor["type"] == "human" {
            let mut person = json!({});
            if let Some(id) = actor["id"].as_str().filter(|s| !s.is_empty()) {
                person["id"] = json!(id);
            }
            if let Some(name) = actor["label"].as_str().filter(|s| !s.is_empty()) {
                person["name"] = json!(name);
            }
            if person.as_object().is_some_and(|o| !o.is_empty()) {
                h["user"] = person;
            }
        }
    })?;
    let identities = q::has(db, "transcript_event_identities")?;
    q::rows(
        db,
        "transcript_events",
        Some(("session_id", id)),
        &["seq"],
        s.limit,
        |r| {
            if r.get("_gap").is_some() {
                return q::push(s, id, "event", r);
            }
            let decoded = if let Some(text) = r["event_json"].as_str() {
                asr_core::jsonl::decode(text).ok()
            } else {
                q::blob(&r["event_zstd"])
                    .and_then(|b| q::decompress(&b, s.limit))
                    .filter(|b| {
                        r["event_utf8_bytes"]
                            .as_u64()
                            .is_none_or(|n| n == b.len() as u64)
                    })
                    .and_then(|b| String::from_utf8(b).ok())
                    .and_then(|b| asr_core::jsonl::decode(&b).ok())
            };
            let Some(mut event) = decoded.filter(Value::is_object) else {
                return q::gap(s, id, "unparseable");
            };
            if event["type"] == "session" {
                native_header(s, id, &event)?;
            }
            if let (Some(ancestor), Some(native)) =
                (ancestor.filter(|_| identities), event["id"].as_str())
            {
                let copied=db.query_row("SELECT EXISTS(SELECT 1 FROM transcript_event_identities WHERE session_id=?1 AND event_id=?2)",rusqlite::params![ancestor,native],|r|r.get::<_,bool>(0))?;
                if copied {
                    event["_copiedFrom"] = json!(ancestor);
                }
            }
            q::push(s, id, "event", event)
        },
    )?;
    // A separate store has no shared transcript order. Its decisions need a post-decision result receipt.
    let shared = path
        .ancestors()
        .find(|p| p.file_name().is_some_and(|s| s == "agents"))
        .and_then(Path::parent)
        .map(|p| p.join("state/openclaw.sqlite"));
    if let Some(shared) = shared.filter(|p| p.is_file()) {
        let shared =
            Connection::open_with_flags(shared, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY)?;
        shared.execute_batch("PRAGMA query_only=ON; PRAGMA cache_size=-4096; BEGIN;")?;
        q::rows(
            &shared,
            "operator_approvals",
            Some(("source_session_id", id)),
            &["approval_id"],
            s.limit,
            |r| q::push(s, id, "approval", r),
        )?;
    }
    // Also support explicitly co-located approval stores in native snapshots.
    if q::has(db, "operator_approvals")? {
        q::rows(
            db,
            "operator_approvals",
            Some(("source_session_id", id)),
            &["approval_id"],
            s.limit,
            |r| q::push(s, id, "approval", r),
        )?;
    }
    q::push(s, id, "node", node)?;
    q::push(s, id, "window", row.clone())
}
fn parts(v: &Value) -> Vec<Value> {
    if let Some(t) = v.as_str() {
        return vec![common::text(t)];
    }
    v.as_array()
        .into_iter()
        .flatten()
        .filter_map(|p| match p["type"].as_str() {
            Some("toolCall") => None,
            Some("thinking") if p["redacted"] == true => {
                Some(json!({"type":"reasoning","visibility":"encrypted"}))
            }
            Some("thinking") => {
                let r = common::reasoning(p["thinking"].as_str(), None);
                Some(r)
            }
            Some("text") => p["text"].as_str().map(common::text),
            Some("image" | "audio" | "resource" | "resource_link") => Some(p.clone()),
            _ => Some(common::vendor_part(Agent::OpenClaw, p)),
        })
        .collect()
}
pub(crate) fn convert(s: &Spool, c: &mut Context, v: &Value) -> Result<()> {
    if q::common(s, c, v)? {
        return Ok(());
    }
    let e = &v["data"];
    if v["table"] == "node" {
        if let Some(mode) = e.get("permissionMode") {
            c.settings(s, json!({"approval":mode}))?;
        }
        return q::vendor(s, c, v);
    }
    if v["table"] == "approval" {
        approval(s, c, e)?;
        return q::vendor(s, c, v);
    }
    if v["table"] != "event" {
        return q::vendor(s, c, v);
    }
    if let Some(owner) = e["_copiedFrom"].as_str() {
        c.source["copiedFrom"] = json!({"session":asr_core::identity::session_ref(c.agent.name(),c.namespace.as_deref(),owner)});
    }
    if let Some(t) = q::time(&e["timestamp"], true) {
        c.source["ts"] = json!(t);
    }
    let native = e["id"].as_str();
    let root = if let Some(old) = e["supersedesEntryId"].as_str() {
        s.entity(&format!("openclaw-root:{old}"))?
            .and_then(|v| v.as_str().map(str::to_owned))
            .or_else(|| Some(old.into()))
    } else {
        native.map(str::to_owned)
    };
    if let (Some(native), Some(root)) = (native, &root) {
        s.save(&format!("openclaw-root:{native}"), &json!(root))?;
    }
    match e["type"].as_str() {
        Some("session") => {}
        Some("thinking_level_change") => c.settings(
            s,
            json!({"modelSettings":{"reasoningEffort":e["thinkingLevel"]}}),
        )?,
        Some("custom") if e["customType"] == "openclaw.system-prompt" => {
            if let Some(tools) = e["data"]["tools"].as_array() {
                let tools: Vec<_> = tools
                    .iter()
                    .filter_map(|t| {
                        let name = t["name"].as_str()?;
                        let mut tool = json!({"name":name});
                        common::copy(&mut tool, "description", t, "description");
                        common::copy(&mut tool, "inputSchema", t, "parameters");
                        Some(tool)
                    })
                    .collect();
                c.info(s, json!({"type":"session_info","tools":tools}))?;
            }
        }
        Some("compaction" | "branch_summary") => {
            if let Some(summary) = e["summary"].as_str() {
                c.emit(s,json!({"type":"message","role":"user","author":"harness","origin":"compaction","content":[common::text(summary)]}),native,None)?;
            }
            if e["historyRetained"] == false {
                c.emit(s, json!({"type":"gap","reason":"not_retained"}), None, None)?;
            }
        }
        Some("message") => {
            let m = &e["message"];
            let role = m["role"].as_str().unwrap_or("");
            let inf = if role == "assistant" && m["provider"] != "openclaw" {
                m["responseId"].as_str().or_else(|| m["turnId"].as_str())
            } else {
                None
            };
            if role == "toolResult" {
                let details = &m["details"];
                let status = if details["openclawSyntheticMissingToolResult"] == true
                    || matches!(
                        details["status"].as_str(),
                        Some("running" | "approval-pending")
                    ) {
                    "unknown"
                } else if details["reason"] == "policy-denied"
                    || details["failureKind"] == "auto-review-denied"
                {
                    "denied"
                } else {
                    q::error_status(&m["isError"])
                };
                let mut r =
                    json!({"type":"tool_result","status":status,"content":parts(&m["content"])});
                if let Some(id) = m["toolCallId"].as_str() {
                    r["callId"] = json!(id);
                }
                if let Some(code) = details["exitCode"].as_i64() {
                    r["exec"]["exitCode"] = json!(code);
                }
                if let Some(output) = details["aggregated"].as_str() {
                    r["exec"]["output"] = json!(output);
                }
                if let Some(duration) = q::count(&details["durationMs"]) {
                    r["durationMs"] = json!(duration);
                }
                // The result names its decision. The link is kept at output only
                // if that decision's store row produced an approval for this call.
                let approval = details["approvalId"]
                    .as_str()
                    .filter(|_| status != "unknown");
                if let Some(approval) = approval {
                    r["approvalId"] = json!(approval);
                }
                q::receipt(
                    s,
                    c,
                    r,
                    root.as_deref(),
                    root.as_ref().map(|id| format!("result:{id}")).as_deref(),
                )?;
                if let Some(approval) = approval {
                    s.save(
                        &format!("approval-position:{approval}"),
                        &json!({"pos":c.pos,"slot":c.slot-1,"callId":m["toolCallId"]}),
                    )?;
                }
                if status == "completed" && details["changed"] == true {
                    if let Some(call) = m["toolCallId"].as_str() {
                        if let Some(tool) = s
                            .entity(&format!("openclaw-tool:{call}"))?
                            .filter(|t| t["ambiguous"] != true)
                            .filter(|t| {
                                matches!(t["call"]["name"].as_str(), Some("write" | "edit"))
                            })
                        {
                            let args = &tool["call"]["arguments"];
                            if let (Some(path), Some(created)) = (
                                args["path"].as_str().or_else(|| args["file_path"].as_str()),
                                details["created"].as_bool(),
                            ) {
                                let mut change = json!({"type":"file_change","path":common::path(path,c.cwd.as_deref()),"status":"applied","callId":call});
                                change["op"] = json!(if created { "add" } else { "modify" });
                                if let Some(patch) = details["diff"].as_str() {
                                    change["patch"] = json!(patch);
                                }
                                c.emit(
                                    s,
                                    change,
                                    None,
                                    root.as_ref().map(|r| format!("file-change:{r}")).as_deref(),
                                )?;
                            }
                        }
                    }
                }
            } else if matches!(role, "user" | "assistant" | "system" | "developer") {
                let mut r = json!({"type":"message","role":role,"content":parts(&m["content"])});
                if role == "assistant" && m["provider"] != "openclaw" {
                    r["author"] = json!("model");
                }
                if m["synthetic"] == true
                    || m["runtimeContext"] == true
                    || m["provenance"]["kind"] == "internal_system"
                {
                    r["author"] = json!("harness");
                    r["origin"] = json!("injected");
                }
                let prov = &m["provenance"];
                if matches!(prov["sourceTool"].as_str(), Some("cron" | "cron_execution")) {
                    r["origin"] = json!("scheduled");
                }
                if prov["kind"] == "inter_session" {
                    r["author"] = json!("agent");
                }
                let sender = &m["__openclaw"]["senderIdentity"];
                if role == "user"
                    && (sender["type"] == "profile" || sender["senderKind"] == "human")
                    && m["synthetic"] != true
                    && m["runtimeContext"] != true
                    && !matches!(
                        prov["kind"].as_str(),
                        Some("inter_session" | "internal_system")
                    )
                {
                    r["author"] = json!("human");
                    if r.get("origin").is_none() {
                        r["origin"] = json!("prompt");
                    }
                    if let Some(id) = sender["id"].as_str().filter(|s| !s.is_empty()) {
                        r["person"] = json!({"id":id});
                    }
                }
                if let Some(inf) = inf {
                    r["inferenceId"] = json!(inf);
                }
                if m["truncated"] == true {
                    r["truncated"] = json!(true);
                    c.loss("source_truncation");
                }
                c.emit(
                    s,
                    r,
                    root.as_deref(),
                    root.as_ref().map(|id| format!("message:{id}")).as_deref(),
                )?;
                for (i, t) in m["content"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter(|p| p["type"] == "toolCall")
                    .enumerate()
                {
                    if let Some(id) = t["id"].as_str() {
                        let key = format!("openclaw-tool:{id}");
                        let owner = root
                            .clone()
                            .unwrap_or_else(|| format!("position:{}", c.pos));
                        let ambiguous = s
                            .entity(&key)?
                            .is_some_and(|old| old["ambiguous"] == true || old["owner"] != owner);
                        s.save(&key, &json!({"call":t,"owner":owner,"ambiguous":ambiguous}))?;
                    }
                    let mut r = json!({"type":"tool_call","callId":t["id"],"requestedBy":"model"});
                    common::copy(&mut r, "name", t, "name");
                    if let Some(args) = t.get("arguments") {
                        r["input"] = args.clone();
                    }
                    if let Some(kind) = match t["name"].as_str() {
                        Some("read") => Some("read"),
                        Some("write" | "edit") => Some("edit"),
                        Some("exec" | "bash" | "bashExecution") => Some("execute"),
                        Some("web_fetch") => Some("fetch"),
                        Some("web_search") => Some("search"),
                        _ => None,
                    } {
                        r["kind"] = json!(kind);
                    }
                    if let Some(inf) = inf {
                        r["inferenceId"] = json!(inf);
                    }
                    c.emit(
                        s,
                        r,
                        None,
                        root.as_ref()
                            .map(|root| format!("call:{root}:{i}"))
                            .as_deref(),
                    )?;
                }
            }
            if let Some(inf) = inf {
                let mut r = json!({"type":"inference"});
                let mut model = json!({});
                common::copy(&mut model, "requested", m, "model");
                common::copy(&mut model, "id", m, "responseModel");
                if model.get("id").is_some() || model.get("requested").is_some() {
                    common::copy(&mut model, "provider", m, "provider");
                    r["model"] = model;
                }
                common::copy(&mut r, "stopReason", m, "stopReason");
                let u = &m["usage"];
                if u["usageReport"]["state"] != "unavailable" {
                    r["usage"] = q::usage(u, "input", "output", "cacheRead", "cacheWrite", false);
                    if let Some(n) = q::count(&u["reasoning"]) {
                        r["usage"]["reasoningTokens"] = json!(n);
                    }
                    if let Some(cost) = q::cost(
                        &u["cost"]["total"],
                        if u["cost"]["source"] == "provider-billed" {
                            "provider_reported"
                        } else {
                            "harness_estimated"
                        },
                    ) {
                        r["cost"] = cost;
                    }
                }
                q::metadata(&mut r, c.agent, "responseId", &json!(inf));
                c.emit(s, r, Some(inf), Some(&format!("inference:{inf}")))?;
            }
        }
        _ => {}
    }
    q::vendor(s, c, v)
}
fn approval(s: &Spool, c: &mut Context, d: &Value) -> Result<()> {
    if d["resolver_kind"] == "system" && d["terminal_reason"] == "storage-corrupt" {
        return Ok(());
    }
    let decision = match d["status"].as_str() {
        Some("allowed") => "approved",
        Some("denied") => "denied",
        Some("expired" | "cancelled") => "cancelled",
        _ => return Ok(()),
    };
    let Some(id) = d["approval_id"].as_str() else {
        return Ok(());
    };
    if s.entity(&format!("approval-emitted:{id}"))?.is_some() {
        return Ok(());
    }
    let Some(position) = s.entity(&format!("approval-position:{id}"))? else {
        c.loss("unpositioned_approvals");
        return Ok(());
    };
    s.save(&format!("approval-emitted:{id}"), &json!(true))?;
    let mut r = json!({"type":"approval","decision":decision,"native":d});
    if let Some(call) = position["callId"].as_str() {
        r["callId"] = json!(call);
    }
    if decision != "cancelled" && d["decision"] == "allow-once" {
        r["scope"] = json!("once");
    }
    q::stamp(&mut r, &d["resolved_at_ms"], true);
    // The result position is established by its receipt. Move it one slot forward.
    let pos = position["pos"].as_u64().unwrap();
    let slot = position["slot"].as_u64().unwrap();
    s.db.execute(
        "UPDATE projected SET slot=-slot-1 WHERE pos=?1 AND slot>=?2",
        rusqlite::params![pos, slot],
    )?;
    s.db.execute(
        "UPDATE projected SET slot=-slot WHERE pos=?1 AND slot<0",
        [pos],
    )?;
    let saved = (c.pos, c.slot, c.source.clone());
    c.pos = pos;
    c.slot = slot;
    c.source = json!({});
    c.emit(s, r, Some(id), None)?;
    (c.pos, c.slot, c.source) = saved;
    Ok(())
}
