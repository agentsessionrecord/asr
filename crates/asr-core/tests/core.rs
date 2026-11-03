use asr_core::{
    identity::{derive_id, encode_component},
    jsonl::{self, Line, Reader},
    ordering::fold_completed,
    state::{effective_input, SessionState},
    Record, Writer,
};
use serde_json::{json, Value};
use std::io::Cursor;
fn header() -> Value {
    json!({"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"com.example.agent"},"sessionId":"synthetic","producer":{"name":"test","version":"1","method":"recorder"},"missing":["model"]})
}

#[test]
fn exact_numbers_unknown_fields_and_nulls_round_trip() {
    for raw in [
        r#"{"type":"inference","id":"i","usage":{"inputTokens":9007199254740993123456789},"_meta":{"com.example.test":{"decimal":1.2345678901234567890123456789,"exponent":9.999999999999e+99}}}"#,
        r#"{"type":"tool_result","id":"r","status":"unknown","input":null}"#,
        r#"{"type":"session_info","id":"s","agentSettings":{"mode":null,"approval":null,"modelSettings":{"temperature":null},"externalSandbox":null}}"#,
        r#"{"type":"com.example.test/new","id":"x","unknown":{"value":0,"false":false}}"#,
    ] {
        let value = jsonl::decode(raw).unwrap();
        let record = Record::from_value(value.clone()).unwrap();
        assert_eq!(serde_json::to_value(record).unwrap(), value);
    }
    let value = jsonl::decode(r#"{"n":1.2345678901234567890123456789}"#).unwrap();
    assert_eq!(value.to_string(), r#"{"n":1.2345678901234567890123456789}"#);
}
#[test]
fn lines_recover_and_defer_tails_with_bounded_buffers() {
    let raw="{\"type\":\"x\",\"id\":\"a\"}\n{\"x\":1,\"x\":2}\n{\"nested\":{\"k\":1,\"k\":2}}\n{}\n{\"tail\":true}";
    let mut reader = Reader::new(Cursor::new(raw), 1024);
    assert!(matches!(reader.read().unwrap(), Some(Line::Record(_))));
    assert!(matches!(reader.read().unwrap(), Some(Line::Malformed)));
    assert!(matches!(reader.read().unwrap(), Some(Line::Malformed)));
    assert!(matches!(reader.read().unwrap(), Some(Line::Record(_))));
    assert!(matches!(reader.read().unwrap(), Some(Line::Incomplete)));
    assert!(reader.read().unwrap().is_none());
    let mut reader = Reader::new(Cursor::new(format!("{}\n{{}}\n", "x".repeat(100_000))), 32);
    assert!(matches!(reader.read().unwrap(), Some(Line::Oversized)));
    assert!(matches!(reader.read().unwrap(), Some(Line::Record(_))));
}
#[test]
fn settings_preserve_omissions_clear_nulls_and_replace_boundaries() {
    let mut state = SessionState::default();
    state.apply(&json!({"type":"session_info","missing":["usage"],"tools":[{"name":"a"}],"agentSettings":{"approval":"ask","asks":"always","modelSettings":{"temperature":0,"reasoningEffort":"high"},"externalSandbox":{"kind":"vm","source":"setting"}}}));
    state.apply(&json!({"type":"session_info","missing":[],"tools":[],"agentSettings":{"mode":"plan","modelSettings":{"reasoningEffort":null},"externalSandbox":{"source":"detected"}}}));
    assert!(state.missing.contains("usage"));
    assert_eq!(state.facts["tools"], json!([]));
    assert_eq!(state.facts["agentSettings"]["approval"], "ask");
    assert!(state.facts["agentSettings"].get("asks").is_none());
    assert_eq!(
        state.facts["agentSettings"]["modelSettings"],
        json!({"temperature":0})
    );
    assert_eq!(
        state.facts["agentSettings"]["externalSandbox"],
        json!({"source":"detected"})
    );
    state.apply(&json!({"type":"session_info","agentSettings":{"modelSettings":null,"approval":null,"externalSandbox":null}}));
    assert!(state.facts["agentSettings"].get("modelSettings").is_none());
    assert!(state.facts["agentSettings"].get("approval").is_none());
}
#[test]
fn folding_uses_completion_time_and_effective_null_input() {
    let mut result = json!({"type":"tool_result","status":"failed","ts":"2026-10-31T12:00:01Z","exec":{"exitCode":1}});
    fold_completed(
        &mut result,
        &json!({"status":"unknown","content":[{"type":"text","text":"out"}],"ts":"2026-10-31T12:00:03Z"}),
    );
    assert_eq!(result["status"], "failed");
    assert_eq!(result["exec"]["exitCode"], 1);
    assert_eq!(result["ts"], "2026-10-31T12:00:03Z");
    fold_completed(&mut result, &json!({"input":null}));
    assert!(result.get("ts").is_none());
    let call = json!({"inputText":"old"});
    assert_eq!(
        effective_input(&call, Some(&result)),
        Some(("input", &Value::Null))
    );
}
#[test]
fn append_only_writer_keeps_prefix_and_rejects_duplicate_results() {
    let mut output = Vec::new();
    let mut writer = Writer::new(&mut output, &header()).unwrap();
    writer
        .append(&json!({"type":"tool_call","id":"c","callId":"run","name":"shell","input":null}))
        .unwrap();
    writer
        .append(
            &json!({"type":"approval","id":"a","callId":"run","decision":"approved","by":"policy"}),
        )
        .unwrap();
    writer.append(&json!({"type":"tool_result","id":"r","callId":"run","status":"unknown","inputText":""})).unwrap();
    assert!(writer
        .append(&json!({"type":"tool_result","id":"r2","callId":"run","status":"unknown"}))
        .is_err());
    assert!(writer.append(&header()).is_err());
    writer.into_inner().unwrap();
    let expected = format!("{}\n", header());
    assert!(output.starts_with(expected.as_bytes()));
    assert_eq!(output.iter().filter(|b| **b == b'\n').count(), 4);
}
#[test]
fn ids_are_framed_unique_and_references_are_encoded() {
    assert_ne!(derive_id(&["a:b", "c"]), derive_id(&["a", "b:c"]));
    assert_eq!(derive_id(&["same"]), derive_id(&["same"]));
    assert_eq!(encode_component("a:%# \u{85}"), "a%3A%25%23%20%C2%85");
    let ids: std::collections::BTreeSet<_> = (0..10000)
        .map(|n| derive_id(&["session", &n.to_string()]))
        .collect();
    assert_eq!(ids.len(), 10000);
}
