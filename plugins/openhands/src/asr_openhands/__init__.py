"""OpenHands HookConfig command-hook projection."""
from __future__ import annotations

from asr_plugin_core import Store, call, command_main, event, native_id, result


class Recorder:
    def __init__(self, output=None, *, full=None):
        self.store = Store("openhands", "openhands-sdk-HookConfig", output, full=full)

    def __call__(self, p: dict, ts: str):
        sid = native_id(p.get("session_id"))
        if not sid:
            return
        hook = p.get("event_type")
        with self.store.transaction(sid, ts, start=hook == "SessionStart", cwd=p.get("working_dir"), extra_missing=("call_correlation", "model_facing_output")) as sink:
            if sink is None:
                return
            if hook == "PreToolUse":
                record = call(sink.call_id(), p.get("tool_name"), hook, p["tool_input"] if "tool_input" in p else ...)
            elif hook == "PostToolUse":
                # HookEvent contains no call ID. Name or proximity cannot pair it.
                record = result(None, "unknown", None, hook, observedResponse=p.get("tool_response"), observedInput=p.get("tool_input"))
            elif hook == "SessionEnd":
                record = {"type": "session_info", "endedAt": ts}
            elif hook == "UserPromptSubmit" and isinstance(p.get("message"), str):
                record = {"type": "message", "role": "user", "content": [{"type": "text", "text": p["message"]}]}
            else:
                record = event(hook)
            sink.append(record)


def main():
    command_main(Recorder)
