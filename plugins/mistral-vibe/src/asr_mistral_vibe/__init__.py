"""Mistral Vibe native command-hook projection."""
from __future__ import annotations

from asr_plugin_core import Store, call, command_main, event, native_id, result


class Recorder:
    def __init__(self, output=None, *, full=None):
        self.store = Store("mistral-vibe", "vibe-command-hooks", output, full=full)

    def __call__(self, p: dict, ts: str):
        sid = native_id(p.get("session_id"))
        if not sid:
            return
        hook = p.get("hook_event_name")
        with self.store.transaction(sid, ts, parent=native_id(p.get("parent_session_id")), extra_missing=("session_lifecycle", "duration", "model_facing_output")) as sink:
            if sink is None:
                return
            cid = native_id(p.get("tool_call_id"))
            if hook == "pre_tool":
                record = call(cid or sink.call_id(), p.get("tool_name"), hook, p["tool_input"] if "tool_input" in p else ...)
            elif hook == "post_tool":
                status = {"success": "completed", "failure": "failed"}.get(p.get("tool_status"), "unknown")
                record = result(cid, status, p.get("tool_output_text"), hook, structuredOutput=p.get("tool_output"))
                if cid and "tool_input" in p:
                    record["input"] = p["tool_input"]
                if isinstance(p.get("tool_error"), str):
                    record["error"] = {"message": p["tool_error"]}
                # duration_ms is a documented placeholder, never execution timing.
            else:
                record = event(hook)
                if hook == "post_agent" and isinstance(p.get("agent_name"), str):
                    sink.append({"type": "session_info", "agentSettings": {"mode": p["agent_name"]}})
            sink.append(record)


def main():
    command_main(Recorder)
