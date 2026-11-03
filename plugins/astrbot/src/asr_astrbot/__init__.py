"""Projection for AstrBot plugin events."""
from asr_plugin_core import Store, call, event, native_id, result


class Recorder:
    def __init__(self, output=None, *, full=None):
        self.store = Store("astrbot", "astrbot-plugin-events", output, full=full)

    def __call__(self, p: dict, ts: str):
        sid = native_id(p.get("session_id"))
        if not sid:
            return
        hook = p.get("hook")
        with self.store.transaction(sid, ts, extra_missing=("call_correlation", "session_lifecycle", "model_facing_output")) as sink:
            if sink is None:
                return
            if p.get("_asr_dropped"):
                sink.append({"type": "gap", "reason": "not_recorded", "detail": "The recorder queue overflowed."})
            if hook == "on_using_llm_tool":
                record = call(sink.call_id(), p.get("tool_name"), hook, p["tool_args"] if "tool_args" in p else ...)
            elif hook == "on_llm_tool_respond":
                output = p.get("tool_result")
                status = "failed" if isinstance(output, dict) and output.get("isError") is True else "completed" if isinstance(output, dict) and output.get("isError") is False else "unknown"
                # End callbacks carry unfiltered request arguments, not necessarily
                # the valid_params passed to the tool. Do not call them effective.
                record = result(None, status, output, hook, requestedInput=p.get("tool_args"))
            elif hook == "on_llm_request" and isinstance(p.get("prompt"), str):
                record = {"type": "message", "role": "user", "content": [{"type": "text", "text": p["prompt"]}]}
            elif hook == "on_agent_done" and isinstance(p.get("completion_text"), str):
                record = {"type": "message", "role": "assistant", "author": "model", "content": [{"type": "text", "text": p["completion_text"]}]}
            else:
                record = event(hook)
            sink.append(record)
