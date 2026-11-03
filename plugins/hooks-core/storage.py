"""One locked append stream per native session; bounded private index sidecar."""

import datetime
from decimal import Decimal
import fcntl
import json
import os
import stat
import time
import hashlib

MAX_STATE = 512 * 1024
MAX_STREAM = 16 * 1024 * 1024


def decode(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate member")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("non-JSON number")

    def integer(text):
        value = int(text)
        return str(value) if abs(value) > 2**53 - 1 else value

    def floating(text):
        value = Decimal(text)
        return text if abs(value) > 2**53 - 1 else float(text)

    return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid,
                      parse_int=integer, parse_float=floating)


def encode(value):
    return (json.dumps(value, ensure_ascii=True, allow_nan=False,
                       separators=(",", ":")) + "\n").encode()


def checked(fd, directory=False):
    info = os.fstat(fd)
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if (not expected(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or (not directory and info.st_nlink != 1)):
        raise ValueError("output must be private and owned by this user")
    return info


def open_file(root, name, flags):
    fd = os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK,
                 0o600, dir_fd=root)
    try:
        checked(fd)
    except BaseException:
        os.close(fd)
        raise
    return fd


def capture(base, session, event, parent, config):
    from content import Content
    from projection import filename, project

    # Required native identities cannot be redacted into invented identities.
    # Refuse an observation if an identity itself contains a known credential.
    guard = Content(False)
    if any(guard.clean(value) != value for value in (session, parent)):
        return
    identities = []
    for payload in [event] + (event.get("tool_calls") if isinstance(event.get("tool_calls"), list) else []):
        if isinstance(payload, dict):
            identities.extend(payload.get(key) for key in ("tool_use_id", "prompt_id", "agent_id", "message_id"))
    if any(isinstance(value, str) and guard.clean(value) != value for value in identities):
        event = {"hook_event_name": event["hook_event_name"],
                 "native_event": event.get("native_event", event["hook_event_name"]),
                 "_redacted": True}
    observed = datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="microseconds").replace("+00:00", "Z")
    stem = filename(session)

    os.makedirs(base, mode=0o700, exist_ok=True)
    root = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    lock = stream = None
    try:
        checked(root, directory=True)
        lock = open_file(root, stem + ".lock", os.O_CREAT | os.O_RDWR)
        deadline = time.monotonic() + 0.1
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    marker = open_file(root, stem + ".lost", os.O_CREAT | os.O_WRONLY)
                    os.close(marker)
                    return
                time.sleep(0.005)
        stream = open_file(root, stem + ".jsonl",
                           os.O_CREAT | os.O_RDWR | os.O_APPEND)
        size = os.fstat(stream).st_size
        try:
            index = open_file(root, stem + ".state.json", os.O_RDONLY)
        except FileNotFoundError:
            if size:
                stop(root, stream, stem, session, observed, config)
                return
            state = {"version": 3, "position": 0, "size": 0,
                     "content": "full" if os.environ.get("ASR_CONTENT") == "full" else "metadata",
                     "calls": {}, "results": {}, "pending": {}, "display": {}}
        else:
            try:
                raw = os.read(index, MAX_STATE + 1)
                if len(raw) > MAX_STATE:
                    stop(root, stream, stem, session, observed, config)
                    return
                try:
                    state = decode(raw)
                except (ValueError, TypeError):
                    stop(root, stream, stem, session, observed, config)
                    return
            finally:
                os.close(index)
        # A crash between the two writes leaves a valid prefix. Never guess
        # identity/revisions from stale state or rewrite complete ASR lines.
        if not isinstance(state, dict):
            stop(root, stream, stem, session, observed, config)
            return
        if state.get("sealed"):
            return
        if (state.get("version") != 3 or state.get("size") != size
                or type(state.get("position")) is not int or state["position"] < 0
                or any(not isinstance(state.get(key), dict) for key in ("calls", "results", "pending", "display"))):
            stop(root, stream, stem, session, observed, config)
            return
        rows = project(session, parent, event, state, observed, config)
        losses = []
        for name in (stem + ".lost", "capture.lost"):
            try:
                marker = open_file(root, name, os.O_RDONLY)
            except FileNotFoundError:
                continue
            os.close(marker)
            losses.append(name)
        if losses:
            gap = {"type": "gap", "id": "hook-" + str(state["position"]),
                   "ts": observed, "reason": "not_recorded",
                   "detail": "One or more concurrent or interrupted hook callbacks were dropped."}
            state["position"] += 1
            rows.insert(1 if size == 0 else 0, gap)
        data = b"".join(encode(row) for row in rows)
        if size + len(data) > MAX_STREAM or len(encode(state)) > MAX_STATE - 1024:
            # Keep a newly-created header even when the very first callback
            # exceeds the cap. A gap must never become the first record.
            header = encode(rows[0]) if size == 0 and rows else b""
            data = header + encode({"type": "gap",
                           "id": "hook-" + str(state["position"]),
                           "reason": "not_recorded", "ts": observed,
                           "detail": "Recorder storage limit reached; capture stopped.",
                           "_meta": {"org.agentsessionrecord.hooks": {"limit": True}}})
            state["position"] += 1
            state["sealed"] = True
            # Drop the in-memory indexes after sealing, to keep state bounded.
            state["calls"] = state["results"] = state["pending"] = state["display"] = {}
        state["size"] = size + len(data)
        if data and os.write(stream, data) != len(data):
            return
        name = stem + ".state.tmp"
        index = open_file(root, name, os.O_CREAT | os.O_WRONLY)
        try:
            os.ftruncate(index, 0)
            raw = encode(state)
            if os.write(index, raw) != len(raw):
                return
        finally:
            os.close(index)
        os.replace(name, stem + ".state.json", src_dir_fd=root, dst_dir_fd=root)
        for loss in losses:
            os.unlink(loss, dir_fd=root)
    finally:
        if stream is not None:
            # Failed projection must not leave an empty .jsonl advertised as a
            # session. No complete line is removed or rewritten here.
            if os.fstat(stream).st_size == 0:
                os.unlink(stem + ".jsonl", dir_fd=root)
            os.close(stream)
        if lock is not None:
            os.close(lock)
        os.close(root)


def stop(root, stream, stem, session, observed, config):
    """Seal inconsistent state once, without rewriting any complete line."""
    size = os.fstat(stream).st_size
    gap = {"type": "gap", "id": "capture-stop-" + hashlib.sha256(str(size).encode()).hexdigest(),
           "ts": observed, "reason": "not_recorded",
           "detail": "Capture stopped after a storage inconsistency."}
    if size and os.pread(stream, 1, size - 1) == b"\n":
        os.write(stream, encode(gap))
    else:
        # The original torn tail stays incomplete. A separate stream makes the
        # stopped capture visible without completing a malformed source line.
        recovery = open_file(root, stem + "-stopped.jsonl", os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            header = {"type": "session", "id": "header", "formatVersion": "0.1",
                      "agent": {"name": config["agent"]}, "sessionId": session,
                      "producer": {"name": "asr-hooks-" + config["agent"], "version": "0.1.0",
                                   "method": "recorder", "source": config["agent"] + "-hooks"},
                      "missing": ["storage_inconsistency", "capture_restart"]}
            os.write(recovery, encode(header) + encode(gap))
        finally:
            os.close(recovery)
    index = open_file(root, stem + ".state.tmp", os.O_CREAT | os.O_WRONLY)
    try:
        os.ftruncate(index, 0)
        os.write(index, encode({"version": 3, "sealed": True}))
    finally:
        os.close(index)
    os.replace(stem + ".state.tmp", stem + ".state.json", src_dir_fd=root, dst_dir_fd=root)
