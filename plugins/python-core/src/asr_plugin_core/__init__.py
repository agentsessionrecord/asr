"""Shared, passive storage for Python agent hook recorders."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import queue
import logging
import signal
import threading
from typing import Any, Callable

from agent_session_record import session_reference as reference
from agent_session_record.content import content_part
from agent_session_record.hooks import VENDOR, EXTENSION
from agent_session_record.privacy import credential_key, credential_values, environment_secrets, redact_text, OPAQUE

LOG = logging.getLogger(__name__)
LOG.addHandler(logging.NullHandler())

MISSING = [
    "reasoning", "usage", "timestamps", "tool_output", "exit_codes", "file_changes",
    "commits", "subagents", "copies", "model", "approvals", "agent_settings", "tools",
    "instructions", "session_user", "message_person", "message_authorship", "triggers",
    "hook_decisions", "hook_input_rewrites", "bounded_capture", "native_record_ids",
    "cost", "message_history", "media", "session_lifecycle", "parent_lineage", "model_facing_output",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def native_id(value: Any) -> str | None:
    if type(value) is int:
        return str(value)
    return value if isinstance(value, str) and value and not any(ord(c) < 32 for c in value) else None


def parts(value: Any) -> list[dict] | None:
    """Keep text and MCP parts only when the source supplies that representation."""
    if isinstance(value, str):
        return [{"type": "text", "text": value}]
    if isinstance(value, dict):
        value = value.get("content")
    if isinstance(value, list) and all(isinstance(p, dict) and isinstance(p.get("type"), str) for p in value):
        return [part if part["type"] in {"thinking", "redacted_thinking"} else content_part(part) for part in value]
    return None


def number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 2**53 - 1


def event(name: str, **facts: Any) -> dict:
    return {"type": VENDOR + "/hook", "_meta": {VENDOR: {"event": name, **facts}}}


def call(call_id: str, name: Any, hook: str, requested: Any = ...) -> dict:
    record = {"type": "tool_call", "callId": call_id, "_meta": {VENDOR: {"event": hook}}}
    if requested is not ...:
        record["_meta"][VENDOR]["requestedInput"] = requested
    if isinstance(name, str):
        record["name"] = name
    return record


def result(call_id: str | None, status: str, output: Any, hook: str, **facts: Any) -> dict:
    record = {"type": "tool_result", "status": status, "_meta": {VENDOR: {"event": hook, **facts}}}
    if call_id:
        record["callId"] = call_id
    content = parts(output)
    if content is not None:
        record["content"] = content
    elif output is not None:
        record["_meta"][VENDOR]["observedOutput"] = output
    return record


def _clean(value: Any, secrets: tuple[str, ...], changed: list[bool], depth: int = 0) -> Any:
    if depth == 0:
        secrets = (*secrets, *credential_values(value))
    if depth > 20:
        changed[0] = True
        return "[omitted]"
    if isinstance(value, str):
        cleaned = redact_text(value, secrets, "[redacted]")
        if len(cleaned) > 16384:
            cleaned = cleaned[:16384]
        changed[0] |= cleaned != value
        return cleaned
    if isinstance(value, dict):
        kind = value.get("type")
        if isinstance(kind, str) and kind in {"thinking", "redacted_thinking", "reasoning"}:
            mapped = content_part(value)
            changed[0] |= any(key in value for key in ("signature", "encrypted_content")) or (
                value.get("visibility") in {"encrypted", "omitted"} and ("text" in value or "summary" in value))
            value = mapped
        output = {}
        for key, item in list(value.items())[:256]:
            if not isinstance(key, str):
                changed[0] = True
                continue
            safe_key = _clean(key, secrets, changed, depth + 1)
            if credential_key(key):
                output[safe_key] = "[redacted]"
                changed[0] = True
            elif key in OPAQUE:
                changed[0] = True
            else:
                output[safe_key] = _clean(item, secrets, changed, depth + 1)
        changed[0] |= len(value) > 256
        return output
    if isinstance(value, (list, tuple)):
        changed[0] |= len(value) > 256
        return [_clean(item, secrets, changed, depth + 1) for item in value[:256]]
    if type(value) is int and abs(value) > 2**53 - 1:
        return str(value)
    if value is None or type(value) in (int, float, bool):
        return value
    changed[0] = True
    return "[omitted]"


class Store:
    """Serialize each session with a bounded lock wait and the ASR writer."""

    def __init__(self, agent: str, source: str, output: str | Path | None = None, *, full: bool | None = None):
        self.agent, self.source = agent, source
        self.output = Path(output or os.environ.get("ASR_OUTPUT_DIR", "")) if output or os.environ.get("ASR_OUTPUT_DIR") else None
        self.full = os.environ.get("ASR_CONTENT") == "full" if full is None else full
        self.secrets = environment_secrets()

    @contextmanager
    def transaction(self, session_id: str, receipt: str, *, start: bool = False, cwd: Any = None, parent: str | None = None, extra_missing: tuple[str, ...] = ()):
        from .storage import transaction
        with transaction(self, session_id, receipt, start=start, cwd=cwd, parent=parent,
                         extra_missing=extra_missing) as writer:
            yield Sink(writer, self, receipt) if writer is not None else None

    def mark_loss(self):
        from .storage import mark_loss
        mark_loss(self.output)


class Sink:
    def __init__(self, writer: Any, store: Store, receipt: str):
        self.writer, self.store, self.receipt = writer, store, receipt
        self.state = writer._adapter_state

    def append(self, record: dict) -> None:
        if getattr(self.writer, "_capture_stopped", False):
            return
        if record.get("type") == "tool_result" and record.get("callId") in self.writer._results:
            return
        for key in ("callId", "turnId"):
            identity_changed = [False]
            _clean(record.get(key), self.store.secrets, identity_changed)
            if identity_changed[0]:
                self.writer.append({"type": "gap", "ts": self.receipt, "reason": "not_recorded", "detail": "A native identifier could not be safely retained."})
                return
        changed = [False]
        if not self.store.full:
            # Retain event identity and outcomes. Content is an explicit opt-in.
            record = dict(record)
            for key in ("content", "input", "inputText", "exec", "error", "native"):
                if key in record:
                    record.pop(key)
                    changed[0] = True
            metadata = record.get("_meta", {}).get(VENDOR, {})
            record["_meta"] = {VENDOR: {key: value for key, value in metadata.items() if key in {"event", "choice", "surface", "agent_id", "agent_type", "child_session_id", "completed", "interrupted", "status"}}}
            if record.get("type") == "message":
                record["content"] = []
        cleaned = _clean(record, self.store.secrets, changed)
        if "agentSettings" in cleaned:
            settings = self.state.get("settings", {})
            supplied = cleaned["agentSettings"]
            if all(key in settings and settings[key] == value for key, value in supplied.items()):
                return
        if changed[0]:
            cleaned["truncated"] = True
            self.writer.update({"ts": self.receipt, "missing": ["redacted_content"]})
        cleaned["ts"] = self.receipt
        from .storage import MAX_STREAM
        if os.fstat(self.writer._fd).st_size + len(json.dumps(cleaned).encode()) > MAX_STREAM - 2048:
            self.writer.append({"type": "gap", "ts": self.receipt, "reason": "not_recorded", "detail": "Recorder storage limit reached. Capture stopped."})
            self.writer._capture_stopped = True
            return
        self.writer.append(cleaned)
        if "agentSettings" in cleaned:
            self.state.setdefault("settings", {}).update(cleaned["agentSettings"])
        if cleaned.get("type") == "tool_call":
            self.state["calls"] = sorted(set(self.state.get("calls", [])) | {cleaned["callId"]})

    def call_id(self) -> str:
        # The writer derives deterministic record IDs from this stream position.
        return "derived-" + str(self.writer.position)


def passive(handler: Callable, payload: dict, receipt: str | None = None) -> None:
    try:
        handler(payload, receipt or now())
    except Exception:
        LOG.warning("ASR callback disabled for this observation")


class Observer:
    """Bounded background work for callbacks inside long-lived agent processes."""

    def __init__(self, handler: Callable, capacity: int = 256):
        self.handler = handler
        self.queue = queue.Queue(capacity)
        self.dropped = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name="asr-recorder")
        self.thread.start()

    def submit(self, payload: dict) -> None:
        try:
            receipt = now()
            # Snapshot mutable hook arguments before the host invokes other hooks.
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
            if len(encoded) > 1024 * 1024:
                self.dropped.set()
                return
            snapshot = json.loads(encoded)
            self.queue.put_nowait((snapshot, receipt))
        except Exception:
            self.dropped.set()

    def _run(self) -> None:
        while True:
            payload, receipt = self.queue.get()
            try:
                if self.dropped.is_set():
                    payload["_asr_dropped"] = True
                    self.dropped.clear()
                passive(self.handler, payload, receipt)
            finally:
                self.queue.task_done()

    def flush(self) -> None:
        """For tests and explicit shutdown, never called by an ordinary callback."""
        self.queue.join()


def command_main(factory: Callable) -> None:
    """Bound capture and leave a loss marker on timeout or oversized input."""
    import sys
    handler = None
    old_handler = signal.getsignal(signal.SIGALRM)
    old_timer = signal.getitimer(signal.ITIMER_REAL)

    def expired(*_):
        raise TimeoutError("Capture deadline")

    try:
        signal.signal(signal.SIGALRM, expired)
        # Schema imports take about 230 ms cold. Leave room inside the host's
        # one-second timeout, including the bounded lock wait and state write.
        signal.setitimer(signal.ITIMER_REAL, 0.75)
        raw = sys.stdin.buffer.read(1024 * 1024 + 1)
        handler = factory()
        if len(raw) > 1024 * 1024:
            handler.store.mark_loss()
            return
        payload = json.loads(raw)
        if isinstance(payload, dict):
            handler(payload, now())
    except Exception:
        signal.setitimer(signal.ITIMER_REAL, 0)
        from .storage import mark_loss
        mark_loss(handler.store.output if handler else os.environ.get("ASR_OUTPUT_DIR"))
        LOG.warning("ASR command observation could not be recorded")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        signal.setitimer(signal.ITIMER_REAL, *old_timer)
