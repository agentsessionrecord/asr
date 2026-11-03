"""Deep Agents command-hook projection."""
from __future__ import annotations

from asr_plugin_core import Store, call, command_main, event, native_id, number, result


class Recorder:
    def __init__(self, output=None, *, full=None):
        self.store = Store("deepagents", "deepagents-code-command-hooks", output, full=full)

    def __call__(self, p: dict, ts: str):
        sid = native_id(p.get("session_id"))
        if not sid:
            return
        hook = p.get("hook_event_name")
        with self.store.transaction(sid, ts, start=hook == "SessionStart" and p.get("source") == "startup", cwd=p.get("cwd")) as sink:
            if sink is None:
                return
            if isinstance(p.get("permission_mode"), str):
                sink.append({"type": "session_info", "agentSettings": {"approval": p["permission_mode"]}})
            cid = native_id(p.get("tool_use_id"))
            if hook == "PreToolUse":
                record = call(cid or sink.call_id(), p.get("tool_name"), hook, p["tool_input"] if "tool_input" in p else ...)
            elif hook in {"PostToolUse", "PostToolUseFailure"}:
                status = "completed" if hook == "PostToolUse" else "interrupted" if p.get("is_interrupt") is True else "failed"
                record = result(cid, status, p.get("tool_response"), hook)
                if cid and "tool_input" in p:
                    record["input"] = p["tool_input"]
                if number(p.get("duration_ms")):
                    record["durationMs"] = p["duration_ms"]
                if hook == "PostToolUseFailure" and isinstance(p.get("error"), str):
                    record["error"] = {"message": p["error"]}
            elif hook == "SessionEnd":
                record = {"type": "session_info", "endedAt": ts}
            elif hook == "UserPromptSubmit" and isinstance(p.get("prompt"), str):
                record = {"type": "message", "role": "user", "content": [{"type": "text", "text": p["prompt"]}]}
            else:
                # Stop is an attempted turn completion. Other hooks may continue it.
                record = event(hook, **{key: p[key] for key in ("agent_id", "agent_type", "notification_type", "message", "source", "reason") if key in p})
            turn = native_id(p.get("prompt_id"))
            if turn:
                record["turnId"] = turn
            sink.append(record)


def main():
    command_main(Recorder)
