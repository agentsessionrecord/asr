"""Passive Hermes observer plugin."""
from __future__ import annotations

from asr_plugin_core import Observer, Store, VENDOR, call, event, native_id, number, result

HOOKS = (
    "on_session_start", "on_session_end", "on_session_finalize", "on_session_reset",
    "pre_llm_call", "post_llm_call", "pre_tool_call", "post_tool_call",
    "pre_approval_request", "post_approval_response", "subagent_start", "subagent_stop",
)
FIELDS = {
    "session_id", "old_session_id", "new_session_id", "turn_id", "tool_call_id", "tool_name",
    "args", "result", "status", "duration_ms", "error_message", "choice", "decided_by",
    "surface", "command", "description", "completed", "interrupted", "reason", "cwd",
    "user_message", "assistant_response", "parent_session_id", "child_session_id",
    "child_role", "child_goal", "child_summary", "middleware_trace", "coalesced",
}


class Recorder:
    def __init__(self, output=None, *, full=None):
        self.store = Store("hermes", "hermes.observer.v1", output, full=full)

    def __call__(self, p: dict, ts: str):
        hook = p.get("hook")
        sid = native_id(p.get("session_id"))
        if not sid and hook in {"subagent_start", "subagent_stop"}:
            sid = native_id(p.get("parent_session_id"))
        if hook == "on_session_reset":
            sid = native_id(p.get("old_session_id"))
        if not sid:
            return
        with self.store.transaction(sid, ts, start=hook == "on_session_start", cwd=p.get("cwd")) as sink:
            if sink is None:
                return
            if p.get("_asr_dropped"):
                sink.append({"type": "gap", "reason": "not_recorded", "detail": "The recorder queue overflowed."})
            cid = native_id(p.get("tool_call_id"))
            if hook == "pre_tool_call":
                record = call(cid or sink.call_id(), p.get("tool_name"), hook, p["args"] if "args" in p else ...)
            elif hook == "post_tool_call":
                status = {"ok": "completed", "error": "failed", "blocked": "denied", "cancelled": "cancelled"}.get(p.get("status"), "unknown")
                record = result(cid, status, p.get("result"), hook, middlewareTrace=p.get("middleware_trace"))
                if cid and "args" in p:
                    record["input"] = p["args"]
                if number(p.get("duration_ms")):
                    record["durationMs"] = p["duration_ms"]
                if isinstance(p.get("error_message"), str):
                    record["error"] = {"message": p["error_message"]}
            elif hook == "post_approval_response":
                choice = p.get("choice")
                decision = {"once": "approved", "session": "approved", "always": "approved", "deny": "denied", "timeout": "cancelled", "cancelled": "cancelled", "smart_approve": "approved", "smart_deny": "denied"}.get(choice)
                if decision is None:
                    record = event(hook, choice=choice)
                else:
                    record = {"type": "approval", "decision": decision, "native": {"choice": choice, "surface": p.get("surface")}}
                    if "coalesced" in p:
                        record["native"]["coalesced"] = p["coalesced"]
                    if cid:
                        record["callId"] = cid
                    elif isinstance(p.get("command"), str):
                        record["subject"] = p["command"]
                    if choice in {"once", "session", "always", "deny"}:
                        record["by"] = "policy" if p.get("coalesced") is True else "user"
                    elif choice in {"smart_approve", "smart_deny"} and p.get("decided_by") == "aux_llm":
                        record["by"] = "classifier"
                    if choice in {"once", "session", "always"}:
                        record["scope"] = choice
            elif hook in {"pre_llm_call", "post_llm_call"}:
                key = "user_message" if hook == "pre_llm_call" else "assistant_response"
                if not isinstance(p.get(key), str):
                    record = event(hook)
                else:
                    record = {"type": "message", "role": "user" if hook == "pre_llm_call" else "assistant", "content": [{"type": "text", "text": p[key]}]}
                    if hook == "post_llm_call":
                        record["author"] = "model"
            elif hook in {"on_session_finalize", "on_session_reset"}:
                record = {"type": "session_info", "endedAt": ts}
            else:
                record = event(hook, **{key: p[key] for key in ("choice", "surface", "child_session_id", "child_role", "child_goal", "child_summary", "completed", "interrupted", "reason") if key in p})
            turn = native_id(p.get("turn_id"))
            if turn:
                record["turnId"] = turn
            sink.append(record)
        child = native_id(p.get("child_session_id"))
        if hook == "subagent_start" and child and child != sid:
            with self.store.transaction(child, ts, start=True, parent=sid) as sink:
                if sink is not None:
                    sink.append(event(hook, child_role=p.get("child_role")))


def register(plugin):
    """Hermes discovers this function through plugin.yaml or its entry point."""
    recorder = Recorder()
    observer = Observer(recorder)
    for hook in HOOKS:
        def callback(_hook=hook, **kwargs):
            try:
                observer.submit({"hook": _hook, **{key: value for key, value in kwargs.items() if key in FIELDS}})
            except Exception:
                pass
            return None
        plugin.register_hook(hook, callback)
    return observer
