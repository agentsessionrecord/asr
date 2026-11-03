"""Portable flat schemas. Nested source data stays exact in JSON strings."""

import pyarrow as pa

TEXT = pa.string()
INT = pa.int64()
BOOL = pa.bool_()
MONEY = pa.decimal128(38, 18)

COMMON = {
    "session_ref": TEXT, "record_id": TEXT, "record_ref": TEXT,
    "position": INT, "ts": TEXT, "turn_id": TEXT, "inference_id": TEXT,
    "original": BOOL, "copied_from_json": TEXT, "truncated": BOOL,
}
USAGE = {
    "input_tokens": INT, "cache_read_tokens": INT, "cache_write_tokens": INT,
    "output_tokens": INT, "reasoning_tokens": INT,
}
COST = {"cost_amount": MONEY, "cost_amount_text": TEXT,
        "cost_currency": TEXT, "cost_source": TEXT}

DEFINITIONS = {
    "sessions": {
        "session_ref": TEXT, "session_id": TEXT, "namespace": TEXT,
        "agent_name": TEXT, "agent_version": TEXT,
        "user_id": TEXT, "user_email": TEXT, "user_name": TEXT, "user_source": TEXT,
        "producer_name": TEXT, "producer_version": TEXT, "producer_method": TEXT,
        "producer_source": TEXT, "started_at": TEXT, "ended_at": TEXT,
        "title": TEXT, "cwd": TEXT, "parent_session": TEXT, "parent_kind": TEXT,
        "repos_json": TEXT, "missing_json": TEXT, "tools_json": TEXT,
        "agent_settings_json": TEXT, "latest_usage_json": TEXT, "latest_cost_json": TEXT,
        "includes_subagents": BOOL, "source_sha256": TEXT, "source_index": INT,
        "record_count": INT,
    },
    "records": {**COMMON, "record_type": TEXT, "raw_json": TEXT},
    "messages": {**COMMON, "role": TEXT, "author": TEXT, "origin": TEXT,
                 "phase": TEXT, "status": TEXT, "from_session": TEXT,
                 "person_json": TEXT, "content_json": TEXT},
    "tool_calls": {
        **COMMON, "call_id": TEXT, "name": TEXT, "kind": TEXT, "requested_by": TEXT,
        "parent_call_id": TEXT, "input_json": TEXT, "input_text": TEXT,
        "locations_json": TEXT, "subagent_json": TEXT, "pairing": TEXT,
        "result_record_id": TEXT, "result_position": INT, "result_original": BOOL,
        "outcome": TEXT, "effective_input_json": TEXT, "effective_input_text": TEXT,
        "result_content_json": TEXT, "result_error_json": TEXT,
        "exec_json": TEXT, "duration_ms_text": TEXT,
    },
    "tool_results": {
        **COMMON, "call_id": TEXT, "paired_call_record_id": TEXT,
        "pairing": TEXT, "status": TEXT, "content_json": TEXT,
        "input_json": TEXT, "input_text": TEXT, "error_json": TEXT,
        "exec_json": TEXT, "duration_ms_text": TEXT, "subagent_json": TEXT,
    },
    "approvals": {
        **COMMON, "call_id": TEXT, "paired_call_record_id": TEXT,
        "decision": TEXT, "decider": TEXT, "scope": TEXT, "subject": TEXT,
        "person_json": TEXT, "native_json": TEXT,
    },
    "file_changes": {
        **COMMON, "call_id": TEXT, "paired_call_record_id": TEXT,
        "path": TEXT, "old_path": TEXT, "op": TEXT, "status": TEXT, "actor": TEXT,
        "base_commit": TEXT, "before_json": TEXT, "after_json": TEXT,
        "patch": TEXT, "edits_json": TEXT,
    },
    "vcs": {
        **COMMON, "call_id": TEXT, "paired_call_record_id": TEXT,
        "action": TEXT, "status": TEXT, "evidence": TEXT, "actor": TEXT,
        "repo": TEXT, "commit_id": TEXT, "commit_prefix": TEXT, "subject": TEXT,
        "parents_json": TEXT, "parent_count": INT, "head_before": TEXT,
        "head_after": TEXT, "rewrites_json": TEXT, "branch": TEXT,
        "remote": TEXT, "pr_json": TEXT,
    },
    "inferences": {
        **COMMON, "model_provider": TEXT, "model_id": TEXT, "model_requested": TEXT,
        "settings_json": TEXT, **USAGE, **COST, "stop_reason": TEXT,
        "duration_ms_text": TEXT, "error_json": TEXT,
    },
    "session_updates": {
        **COMMON, "title": TEXT, "ended_at": TEXT, "repos_json": TEXT,
        "missing_json": TEXT, "tools_json": TEXT,
        "usage_json": TEXT, "cost_json": TEXT, "includes_subagents": BOOL,
        **USAGE, **COST,
    },
    "settings_changes": {**COMMON, "update_json": TEXT, "effective_json": TEXT},
    "gaps": {**COMMON, "reason": TEXT, "count": INT, "detail": TEXT},
    "links": {
        "session_ref": TEXT, "record_id": TEXT, "position": INT, "kind": TEXT,
        "target_session": TEXT, "target_record": TEXT, "resolved": BOOL,
    },
    "diagnostics": {"source_index": INT, "line": INT, "code": TEXT, "severity": TEXT},
}

SCHEMAS = {
    name: pa.schema(columns).with_metadata({b"asr.tables.version": b"1"})
    for name, columns in DEFINITIONS.items()
}
