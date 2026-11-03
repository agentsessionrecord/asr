use super::*;
use asr_core::state::effective_input;
use clap::Args;
use reqwest::{blocking::Client, redirect::Policy, Url};
use std::{
    io::Read,
    path::PathBuf,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

#[derive(Args)]
pub struct Options {
    pub input: PathBuf,
    #[arg(long)]
    pub inference: String,
    /// Private JSON provider settings with protocol, baseUrl and optional apiKey.
    #[arg(long)]
    pub provider_settings: PathBuf,
    #[arg(long)]
    pub out: PathBuf,
    #[arg(long)]
    pub model: Option<String>,
    #[arg(long)]
    pub system_prompt_file: Option<PathBuf>,
    /// One recorded setting override, for example temperature=0.
    #[arg(long = "setting")]
    pub settings: Vec<String>,
    #[arg(long, default_value = "replay")]
    pub variant: String,
    #[arg(long, default_value_t = 1)]
    pub run_number: usize,
}
struct Provider {
    protocol: String,
    endpoint: Url,
    key: Option<String>,
}
fn provider(path: &Path) -> Result<Provider> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let metadata = fs::symlink_metadata(path)?;
        if !metadata.is_file() || metadata.permissions().mode() & 0o077 != 0 {
            return Err("provider settings must be a private regular file (mode 600)".into());
        }
    }
    let raw = fs::read_to_string(path).map_err(|_| "provider settings could not be read")?;
    let config = asr_core::jsonl::decode(&raw).map_err(|_| "invalid provider settings JSON")?;
    let protocol = text(&config, "protocol")
        .filter(|p| matches!(*p, "openai" | "anthropic"))
        .ok_or("protocol must be openai or anthropic")?
        .to_owned();
    // There is no default endpoint and no credential or proxy fallback from the environment.
    let mut endpoint = Url::parse(text(&config, "baseUrl").ok_or("explicit baseUrl is required")?)
        .map_err(|_| "invalid provider baseUrl")?;
    let loopback = matches!(endpoint.host_str(), Some("127.0.0.1" | "[::1]"));
    if !endpoint.username().is_empty()
        || endpoint.password().is_some()
        || endpoint.query().is_some()
        || endpoint.fragment().is_some()
        || endpoint.host_str().is_none()
        || !(endpoint.scheme() == "https" || (endpoint.scheme() == "http" && loopback))
    {
        return Err("provider baseUrl requires HTTPS or a numeric loopback HTTP host, without credentials, query or fragment".into());
    }
    let suffix = if protocol == "openai" {
        "chat/completions"
    } else {
        "messages"
    };
    endpoint.set_path(&format!(
        "{}/{}",
        endpoint.path().trim_end_matches('/'),
        suffix
    ));
    let key = text(&config, "apiKey").map(str::to_owned);
    Ok(Provider {
        protocol,
        endpoint,
        key,
    })
}
fn string_content(record: &Value, losses: &mut std::collections::BTreeSet<String>) -> String {
    let mut result = String::new();
    for p in record["content"].as_array().into_iter().flatten() {
        if p["type"] == "text" {
            if let Some(s) = text(p, "text") {
                result.push_str(s);
            }
        } else {
            losses.insert("replay_content_parts".into());
        }
    }
    result
}
fn settings(options: &Options, inference: &Value) -> Result<Value> {
    let mut result = inference.get("settings").cloned().unwrap_or(json!({}));
    if !result.is_object() {
        return Err("invalid inference settings".into());
    }
    for setting in &options.settings {
        let (key, raw) = setting.split_once('=').ok_or("setting requires KEY=JSON")?;
        if ![
            "temperature",
            "maxOutputTokens",
            "reasoningEffort",
            "serviceTier",
        ]
        .contains(&key)
        {
            return Err("unsupported setting override".into());
        }
        let value = asr_core::jsonl::decode(raw).map_err(|_| "invalid setting override JSON")?;
        if value.is_null() {
            result.as_object_mut().unwrap().remove(key);
        } else {
            result[key] = value;
        }
    }
    for (key, v) in result.as_object().unwrap() {
        let valid = match key.as_str() {
            "temperature" => v.is_number(),
            "maxOutputTokens" => v.as_u64().is_some_and(|n| n <= 9_007_199_254_740_991),
            "reasoningEffort" | "serviceTier" => v.is_string(),
            _ => false,
        };
        if !valid {
            return Err("unsupported or invalid model setting".into());
        }
    }
    Ok(result)
}
fn build_request(
    stream: &Stream,
    cutoff: usize,
    model: &str,
    settings: &Value,
    system: Option<&str>,
    protocol: &str,
    losses: &mut std::collections::BTreeSet<String>,
) -> Result<Value> {
    let mut state = asr_core::state::SessionState::default();
    let mut messages = Vec::new();
    let mut systems = Vec::new();
    if let Some(s) = system {
        if protocol == "openai" {
            messages.push(json!({"role":"system","content":s}));
        } else {
            systems.push(json!({"type":"text","text":s}));
        }
    }
    for r in &stream.records[..cutoff] {
        state.apply(r);
        match text(r, "type") {
            Some("message") => {
                let role = text(r, "role").unwrap_or("user");
                if !matches!(role, "user" | "assistant" | "system" | "developer") {
                    losses.insert("replay_message_roles".into());
                    continue;
                }
                if system.is_some() && role == "system" {
                    continue;
                }
                let content = string_content(r, losses);
                if protocol == "anthropic" && matches!(role, "system" | "developer") {
                    systems.push(json!({"type":"text","text":content}));
                    if role == "developer" {
                        losses.insert("replay_developer_role".into());
                    }
                } else {
                    messages.push(json!({"role":role,"content":content}));
                }
            }
            Some("tool_call") => {
                let Some(call) = text(r, "callId") else {
                    continue;
                };
                if stream.unique_call(call).is_none() {
                    return Err("cannot replay context with ambiguous tool call IDs".into());
                }
                let Some(name) = text(r, "name") else {
                    losses.insert("replay_tool_names".into());
                    continue;
                };
                let result = stream.result(call).filter(|result| {
                    stream.records[..cutoff]
                        .iter()
                        .any(|r| std::ptr::eq(r, *result))
                });
                let input = effective_input(r, result)
                    .map(|(kind, v)| {
                        if kind == "input" {
                            v.clone()
                        } else {
                            v.as_str()
                                .and_then(|s| asr_core::jsonl::decode(s).ok())
                                .unwrap_or_else(|| {
                                    losses.insert("replay_string_arguments".into());
                                    json!({"text":v})
                                })
                        }
                    })
                    .unwrap_or_else(|| {
                        losses.insert("replay_tool_input".into());
                        json!({})
                    });
                if protocol == "openai" {
                    messages.push(json!({"role":"assistant","tool_calls":[{"id":call,"type":"function","function":{"name":name,"arguments":serde_json::to_string(&input)?}}]}));
                } else {
                    messages.push(json!({"role":"assistant","content":[{"type":"tool_use","id":call,"name":name,"input":input}]}));
                }
                if result.is_none() {
                    return Err(
                        "cannot replay context with a tool call lacking a unique earlier result"
                            .into(),
                    );
                }
            }
            Some("tool_result") => {
                let Some(call) = text(r, "callId")
                    .filter(|id| stream.result(id).is_some_and(|v| std::ptr::eq(v, r)))
                else {
                    losses.insert("replay_unpaired_results".into());
                    continue;
                };
                if !stream.records[..cutoff]
                    .iter()
                    .any(|r| r["type"] == "tool_call" && text(r, "callId") == Some(call))
                {
                    losses.insert("replay_unpaired_results".into());
                    continue;
                }
                let content = string_content(r, losses);
                if protocol == "openai" {
                    messages.push(json!({"role":"tool","tool_call_id":call,"content":content}));
                } else {
                    messages.push(json!({"role":"user","content":[{"type":"tool_result","tool_use_id":call,"content":content}]}));
                }
            }
            _ => {}
        }
    }
    let mut request = json!({"model":model,"messages":messages,"stream":false});
    if protocol == "anthropic" && !systems.is_empty() {
        request["system"] = json!(systems);
    }
    let mappings = if protocol == "openai" {
        [
            ("temperature", "temperature"),
            ("maxOutputTokens", "max_completion_tokens"),
            ("reasoningEffort", "reasoning_effort"),
            ("serviceTier", "service_tier"),
        ]
    } else {
        [
            ("temperature", "temperature"),
            ("maxOutputTokens", "max_tokens"),
            ("reasoningEffort", "output_config"),
            ("serviceTier", "service_tier"),
        ]
    };
    for (src, dest) in mappings {
        if let Some(v) = settings.get(src) {
            request[dest] = if protocol == "anthropic" && src == "reasoningEffort" {
                json!({"effort":v})
            } else {
                v.clone()
            };
        }
    }
    if protocol == "anthropic" && request.get("max_tokens").is_none() {
        return Err(
            "Anthropic replay requires recorded maxOutputTokens or an explicit override".into(),
        );
    }
    if let Some(tools) = state.facts["tools"].as_array() {
        let mut offered = Vec::new();
        for t in tools {
            let Some(name) = text(t, "name") else {
                continue;
            };
            let Some(schema) = t.get("inputSchema") else {
                losses.insert("replay_tool_schema".into());
                continue;
            };
            let mut tool = if protocol == "openai" {
                json!({"type":"function","function":{"name":name,"parameters":schema}})
            } else {
                json!({"name":name,"input_schema":schema})
            };
            if let Some(description) = t.get("description") {
                if protocol == "openai" {
                    tool["function"]["description"] = description.clone();
                } else {
                    tool["description"] = description.clone();
                }
            }
            offered.push(tool);
        }
        if !offered.is_empty() {
            request["tools"] = json!(offered);
        }
    } else {
        losses.insert("tools".into());
    }
    Ok(request)
}
fn response_records(
    protocol: &str,
    response: &Value,
    model: &str,
    settings: &Value,
    duration: u128,
) -> Result<Vec<Value>> {
    let id = text(response, "id")
        .filter(|id| asr_core::identity::valid_id(id))
        .unwrap_or("replay-inference");
    let id = if id.starts_with("history-")
        || ["replay-header", "variant-instructions", "replay-reply"].contains(&id)
        || id.starts_with("replay-tool-")
    {
        asr_core::identity::derive_id(&["inference", id])
    } else {
        id.to_owned()
    };
    let mut inference = json!({"type":"inference","id":id,"model":{"requested":model},"settings":settings,"durationMs":duration.min(9_007_199_254_740_991) as u64,"ts":chrono::Utc::now().to_rfc3339()});
    if let Some(served) = response.get("model").filter(|v| v.is_string()) {
        inference["model"]["id"] = served.clone();
    }
    let usage = &response["usage"];
    let mut normalized = json!({});
    let mapping = if protocol == "openai" {
        [
            ("prompt_tokens", "inputTokens"),
            ("completion_tokens", "outputTokens"),
        ]
    } else {
        [
            ("input_tokens", "inputTokens"),
            ("output_tokens", "outputTokens"),
        ]
    };
    for (src, dest) in mapping {
        if let Some(n) = usage[src].as_u64().filter(|n| *n <= 9_007_199_254_740_991) {
            normalized[dest] = json!(n);
        }
    }
    if protocol == "anthropic" {
        let mut total = normalized["inputTokens"].as_u64();
        for (src, dest) in [
            ("cache_read_input_tokens", "cacheReadTokens"),
            ("cache_creation_input_tokens", "cacheWriteTokens"),
        ] {
            if let Some(n) = usage[src].as_u64().filter(|n| *n <= 9_007_199_254_740_991) {
                normalized[dest] = json!(n);
                total = total.and_then(|t| t.checked_add(n));
            } else if usage.get(src).is_some() {
                total = None;
            }
        }
        if let Some(n) = total.filter(|n| *n <= 9_007_199_254_740_991) {
            normalized["inputTokens"] = json!(n);
        } else {
            normalized.as_object_mut().unwrap().remove("inputTokens");
        }
    } else {
        for (value, dest) in [
            (
                &usage["prompt_tokens_details"]["cached_tokens"],
                "cacheReadTokens",
            ),
            (
                &usage["completion_tokens_details"]["reasoning_tokens"],
                "reasoningTokens",
            ),
        ] {
            if let Some(n) = value.as_u64().filter(|n| *n <= 9_007_199_254_740_991) {
                normalized[dest] = json!(n);
            }
        }
    }
    let count_paths = [
        "/prompt_tokens",
        "/completion_tokens",
        "/input_tokens",
        "/output_tokens",
        "/cache_read_input_tokens",
        "/cache_creation_input_tokens",
        "/prompt_tokens_details/cached_tokens",
        "/completion_tokens_details/reasoning_tokens",
    ];
    let mut exceptional = serde_json::Map::new();
    for path in count_paths {
        if let Some(v) = usage.pointer(path) {
            if v.as_u64().is_none_or(|n| n > 9_007_199_254_740_991) {
                exceptional.insert(
                    path.to_owned(),
                    json!(v
                        .as_str()
                        .map(str::to_owned)
                        .unwrap_or_else(|| v.to_string())),
                );
            }
        }
    }
    if protocol == "anthropic"
        && normalized.get("inputTokens").is_none()
        && usage.get("input_tokens").is_some()
    {
        for key in [
            "input_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        ] {
            if let Some(value) = usage.get(key) {
                exceptional.insert(key.into(), json!(value.to_string()));
            }
        }
        let total = [
            "input_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        ]
        .iter()
        .try_fold(0u128, |sum, key| {
            if let Some(v) = usage.get(*key) {
                v.as_u64().map(|n| sum + u128::from(n))
            } else {
                Some(sum)
            }
        });
        if let Some(total) = total {
            exceptional.insert("inclusiveInputTokens".into(), json!(total.to_string()));
        }
    }
    if !exceptional.is_empty() {
        inference["_meta"] = json!({META:{"providerUsage":exceptional,"usageIncomplete":true}});
    }
    if normalized.as_object().is_some_and(|o| !o.is_empty()) {
        inference["usage"] = normalized;
    }
    let mut records = Vec::new();
    let mut content = Vec::new();
    let mut calls = Vec::new();
    if protocol == "openai" {
        let choice = response["choices"]
            .as_array()
            .and_then(|a| a.first())
            .ok_or("provider response lacks a choice")?;
        if let Some(reason) = choice.get("finish_reason").filter(|v| v.is_string()) {
            inference["stopReason"] = reason.clone();
        }
        let message = &choice["message"];
        if let Some(s) = text(message, "content") {
            content.push(json!({"type":"text","text":s}));
        } else if message.get("content").is_some_and(|v| !v.is_null()) {
            return Err("unsupported response content".into());
        }
        for (i, call) in message["tool_calls"]
            .as_array()
            .into_iter()
            .flatten()
            .enumerate()
        {
            let mut r = json!({"type":"tool_call","id":format!("replay-tool-{i}"),"inferenceId":id,"callId":text(call,"id").unwrap_or(&format!("replay-call-{i}")),"requestedBy":"model"});
            if let Some(name) = call["function"].get("name") {
                r["name"] = name.clone();
            }
            let args = text(&call["function"], "arguments").unwrap_or("");
            if let Ok(input) = asr_core::jsonl::decode(args) {
                r["input"] = input;
            } else {
                r["inputText"] = json!(args);
            }
            calls.push(r);
        }
    } else {
        let parts = response["content"]
            .as_array()
            .ok_or("provider response lacks content")?;
        if let Some(reason) = response.get("stop_reason").filter(|v| v.is_string()) {
            inference["stopReason"] = reason.clone();
        }
        for (i, p) in parts.iter().enumerate() {
            match text(p,"type") {
                Some("text")=>content.push(json!({"type":"text","text":p["text"]})),
                Some("thinking")=>content.push(match text(p,"thinking").filter(|s| !s.is_empty()) {
                    Some(s)=>json!({"type":"reasoning","visibility":"summary","summary":[s]}),
                    None=>json!({"type":"reasoning","visibility":"omitted"}),
                }),
                Some("redacted_thinking")=>content.push(json!({"type":"reasoning","visibility":"encrypted"})),
                Some("tool_use")=>calls.push(json!({"type":"tool_call","id":format!("replay-tool-{i}"),"inferenceId":id,"callId":p["id"],"name":p["name"],"input":p["input"],"requestedBy":"model"})),
                _=>return Err("unsupported provider response part".into()),
            }
        }
    }
    records.push(inference);
    if !content.is_empty() {
        records.push(json!({"type":"message","id":"replay-reply","inferenceId":id,"role":"assistant","author":"model","content":content}));
    }
    records.extend(calls);
    let receipt = records[0]["ts"].clone();
    for record in &mut records {
        record["ts"] = receipt.clone();
    }
    Ok(records)
}

fn context_cutoff(stream: &Stream, index: usize) -> (usize, bool) {
    let id = text(&stream.records[index], "id");
    if let Some(output) = stream
        .records
        .iter()
        .position(|r| text(r, "inferenceId") == id)
    {
        return (output.min(index), false);
    }
    // Without recorded output links, completion order cannot establish the exact
    // request boundary. Keep inputs before the first possible model output after
    // the previous call and discard everything from that output onward.
    let start = stream.records[..index]
        .iter()
        .rposition(|r| r["type"] == "inference")
        .map_or(1, |i| i + 1);
    let cutoff = stream.records[start..index]
        .iter()
        .position(|r| {
            (r["type"] == "message" && r["role"] == "assistant")
                || (r["type"] == "tool_call" && r["requestedBy"] == "model")
        })
        .map_or(index, |i| start + i);
    (cutoff, true)
}

pub fn run(options: Options) -> Result<Value> {
    if options.out.exists() {
        return Err("output already exists".into());
    }
    if crate::validator().is_none() {
        return Err("Node validator not found".into());
    }
    let directory = options
        .out
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    let _destination_check = tempfile::NamedTempFile::new_in(directory)
        .map_err(|_| "output directory is not writable")?;
    let stream = Stream::load(&options.input)?;
    let index = stream
        .records
        .iter()
        .position(|r| r["type"] == "inference" && text(r, "id") == Some(options.inference.as_str()))
        .ok_or("inference not found")?;
    let original = &stream.records[index];
    let (cutoff, unlinked) = context_cutoff(&stream, index);
    let source = stream.session();
    let model = options
        .model
        .as_deref()
        .or_else(|| text(&original["model"], "requested"))
        .or_else(|| text(&original["model"], "id"))
        .ok_or("recorded model is unknown, supply --model")?;
    let settings = settings(&options, original)?;
    let system = options
        .system_prompt_file
        .as_ref()
        .map(fs::read_to_string)
        .transpose()
        .map_err(|_| "system prompt could not be read")?;
    let provider = provider(&options.provider_settings)?;
    let mut losses = stream.state().missing;
    losses.extend(["replay_context", "cost", "timestamps"].map(str::to_owned));
    if unlinked {
        losses.insert("replay_unlinked_outputs".into());
    }
    if !stream.warnings.is_empty() {
        losses.insert("history".into());
    }
    let mut request = build_request(
        &stream,
        cutoff,
        model,
        &settings,
        system.as_deref(),
        &provider.protocol,
        &mut losses,
    )?;
    let mut scrubber = redact::Scrubber::new();
    scrubber.add_secret(provider.key.as_deref());
    if scrubber.apply(&mut request) {
        losses.insert("redacted_content".into());
    }
    let client = Client::builder()
        .redirect(Policy::none())
        .no_proxy()
        .timeout(Duration::from_secs(60))
        .build()
        .map_err(|_| "HTTP client setup failed")?;
    let mut call = client.post(provider.endpoint).json(&request);
    if provider.protocol == "anthropic" {
        call = call.header("anthropic-version", "2023-06-01");
        if let Some(key) = &provider.key {
            call = call.header("x-api-key", key);
        }
    } else if let Some(key) = &provider.key {
        call = call.bearer_auth(key);
    }
    let start = Instant::now();
    let received = call.send();
    let receipt = chrono::Utc::now().to_rfc3339();
    let mut code = None;
    let parsed: Result<Vec<Value>> = (|| {
        let response = received.map_err(|_| "provider connection failed")?;
        if !response.status().is_success() {
            code = Some(response.status().as_u16());
            return Err("provider HTTP error".into());
        }
        let mut bytes = Vec::new();
        response
            .take((LIMIT + 1) as u64)
            .read_to_end(&mut bytes)
            .map_err(|_| "provider response read failed")?;
        if bytes.len() > LIMIT {
            return Err("provider response exceeds limit".into());
        }
        let response = std::str::from_utf8(&bytes)
            .ok()
            .and_then(|s| asr_core::jsonl::decode(s).ok())
            .ok_or("invalid provider response")?;
        response_records(
            &provider.protocol,
            &response,
            model,
            &settings,
            start.elapsed().as_millis(),
        )
    })();
    let failed = parsed.is_err();
    let mut new_records = parsed.unwrap_or_else(|_| vec![json!({"type":"inference","id":"replay-inference","ts":receipt,"model":{"requested":model},"settings":settings,"error":{"code":code,"message":"Replay request failed"},"durationMs":start.elapsed().as_millis().min(9_007_199_254_740_991) as u64})]);
    if code.is_none() && new_records[0]["error"].is_object() {
        new_records[0]["error"]
            .as_object_mut()
            .unwrap()
            .remove("code");
    }
    if new_records[0]["usage"].get("inputTokens").is_none()
        || new_records[0]["usage"].get("outputTokens").is_none()
        || new_records[0]["_meta"][META]["usageIncomplete"] == true
    {
        losses.insert("usage".into());
    }
    let session_id = format!(
        "replay-{}-{}",
        std::process::id(),
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos()
    );
    let mut header = json!({"type":"session","id":"replay-header","formatVersion":"0.1","agent":{"name":"org.agentsessionrecord.replay","version":VERSION},"sessionId":session_id,
        "producer":{"name":"asr-replay","version":VERSION,"method":"recorder","source":if provider.protocol=="openai" {"openai-chat-completions"} else {"anthropic-messages"}},
        "parent":{"session":source,"kind":"fork"},"missing":losses,"_meta":{META:{"variant":options.variant,"run":options.run_number,"sourceInference":cite(&source,original),"context":"reconstructed"}}});
    let last_shared = stream.records[1..cutoff]
        .iter()
        .rev()
        .find(|r| system.is_none() || r["role"] != "system");
    if let Some(r) = last_shared {
        header["parent"]["record"] = r["id"].clone();
    }
    header["_meta"][META]["sourceContext"] = json!({});
    for field in ["cwd", "repos"] {
        if let Some(v) = stream.records[0].get(field) {
            header["_meta"][META]["sourceContext"][field] = v.clone();
        }
    }
    let mut records = vec![header];
    if let Some(s) = &system {
        records.push(json!({"type":"message","id":"variant-instructions","role":"system","author":"harness","origin":"instructions","content":[{"type":"text","text":s}]}));
    }
    for (i, r) in stream.records[1..cutoff].iter().enumerate() {
        if system.is_some() && r["type"] == "message" && r["role"] == "system" {
            continue;
        }
        let mut copy = r.clone();
        copy["copiedFrom"] = json!({"session":source,"record":r["id"]});
        // Local IDs remain distinct from new provider IDs, with local inference links remapped.
        copy["id"] = json!(format!("history-{i}"));
        if let Some(id) = text(r, "inferenceId") {
            if let Some(j) = stream.records[1..cutoff]
                .iter()
                .position(|r| text(r, "id") == Some(id))
            {
                copy["inferenceId"] = json!(format!("history-{j}"));
            }
        }
        for field in ["callId", "parentCallId"] {
            if let Some(id) = text(r, field) {
                copy[field] = json!(asr_core::identity::derive_id(&["history-call", id]));
            }
        }
        records.push(copy);
    }
    records.append(&mut new_records);
    let mut redacted = false;
    for r in &mut records {
        if scrubber.apply(r) {
            r["truncated"] = json!(true);
            redacted = true;
        }
    }
    if redacted {
        records[0]["missing"]
            .as_array_mut()
            .unwrap()
            .push(json!("redacted_content"));
    }
    let mut report = write_session(&options.out, &records)?;
    report["requestFailed"] = json!(failed);
    report["source"] = stream.diagnostics();
    report["context"] = json!("reconstructed");
    report["contextDetail"] = json!("The rebuilt request and tool list are approximate unless the source captured the exact request.");
    report["unlinkedOutputs"] = json!(unlinked);
    scrubber.apply(&mut report);
    Ok(report)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn first_unlinked_model_tool_request_is_excluded() {
        let stream = Stream {
            records: vec![
                json!({"type":"session","id":"header"}),
                json!({"type":"message","id":"prompt","role":"user","content":[{"type":"text","text":"input"}]}),
                json!({"type":"tool_call","id":"answer","callId":"call","name":"shell","requestedBy":"model","input":{"command":"recorded answer"}}),
                json!({"type":"inference","id":"selected"}),
            ],
            warnings: Vec::new(),
            sha256: String::new(),
        };
        let (cutoff, unlinked) = context_cutoff(&stream, 3);
        assert_eq!((cutoff, unlinked), (2, true));
        let request = build_request(
            &stream,
            cutoff,
            "model",
            &json!({}),
            None,
            "openai",
            &mut Default::default(),
        )
        .unwrap();
        assert_eq!(
            request["messages"],
            json!([{"role":"user","content":"input"}])
        );
    }

    #[test]
    fn empty_anthropic_thinking_is_omitted_and_has_no_signature() {
        let records = response_records(
            "anthropic",
            &json!({"content":[{"type":"thinking","thinking":"","signature":"opaque"}]}),
            "model",
            &json!({}),
            0,
        )
        .unwrap();
        assert_eq!(
            records[1]["content"],
            json!([{"type":"reasoning","visibility":"omitted"}])
        );
        assert!(!serde_json::to_string(&records).unwrap().contains("opaque"));
    }
}
