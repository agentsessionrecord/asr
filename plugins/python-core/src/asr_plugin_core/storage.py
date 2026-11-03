"""Private incremental indexes for locked, bounded command-hook streams."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import stat
import time

MAX_STREAM = 16 * 1024 * 1024
MAX_STATE = 512 * 1024
LOG = logging.getLogger(__name__)
LOG.addHandler(logging.NullHandler())


def private_open(path, flags):
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or info.st_nlink != 1):
        os.close(fd)
        raise ValueError("Expected a private regular file")
    return fd


def mark_loss(output, name="capture.lost"):
    try:
        if output:
            output = Path(output)
            output.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = private_open(output / name, os.O_CREAT | os.O_WRONLY)
            os.close(fd)
    except Exception:
        LOG.warning("ASR loss marker could not be written")


def save(path, state):
    raw = json.dumps(state, ensure_ascii=True, separators=(",", ":")).encode()
    fd = private_open(path.with_suffix(".tmp"), os.O_CREAT | os.O_WRONLY)
    try:
        os.ftruncate(fd, 0)
        write_all(fd, raw)
    finally:
        os.close(fd)
    os.replace(path.with_suffix(".tmp"), path)


def write_all(fd, data):
    remaining = memoryview(data)
    while remaining:
        count = os.write(fd, remaining)
        if count <= 0:
            raise OSError("No write progress")
        remaining = remaining[count:]


def seal(path, index, store, session, receipt, reason):
    """A bad index never authorizes a guessed append position or a rewrite."""
    fd = private_open(path, os.O_RDWR | os.O_APPEND)
    try:
        size = os.fstat(fd).st_size
        complete = size and os.pread(fd, 1, size - 1) == b"\n"
        gap = {"type": "gap", "id": "asr-stop-" + hashlib.sha256(str(size).encode()).hexdigest(),
               "ts": receipt, "reason": "not_recorded", "detail": reason}
        if complete:
            write_all(fd, (json.dumps(gap, separators=(",", ":")) + "\n").encode())
        else:
            # A torn line must remain incomplete. Declare the loss in a separate
            # capture of the same session rather than completing corrupt JSON.
            from agent_session_record import Writer
            from agent_session_record.hooks import EXTENSION
            fallback = path.with_name(path.stem + "-stopped.jsonl")
            try:
                with Writer(fallback, {"agent": {"name": store.agent}, "sessionId": session,
                            "producer": {"name": "asr-hooks-" + store.agent, "version": "0.1.0",
                                         "method": "recorder", "source": store.source},
                            "extensions": [EXTENSION], "missing": ["capture_restart", "storage_inconsistency"]}) as writer:
                    writer.append(gap)
            except FileExistsError:
                pass
        save(index, {"version": 1, "sealed": True})
    finally:
        os.close(fd)


@contextmanager
def transaction(store, session, receipt, *, start=False, cwd=None, parent=None, extra_missing=()):
    from agent_session_record import Writer
    from . import MISSING, EXTENSION, _clean, native_id, reference
    lock = writer = None
    yielded = False
    path = index = marker = None
    try:
        changed = [False]
        _clean(session, store.secrets, changed)
        if store.output is None or native_id(session) is None or changed[0]:
            yielded = True
            yield None
            return
        store.output.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = store.output.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Expected a private output directory")
        stem = store.agent + "-" + hashlib.sha256(session.encode()).hexdigest()
        path = store.output / (stem + ".jsonl")
        index = store.output / (stem + ".state.json")
        marker = store.output / (stem + ".lost")
        lock = private_open(store.output / (stem + ".lock"), os.O_CREAT | os.O_RDWR)
        deadline = time.monotonic() + 0.1
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    mark_loss(store.output, marker.name)
                    yielded = True
                    yield None
                    return
                time.sleep(0.005)
        if path.exists():
            try:
                state_fd = private_open(index, os.O_RDONLY)
                try:
                    state = json.loads(os.read(state_fd, MAX_STATE + 1))
                finally:
                    os.close(state_fd)
                if state.get("sealed"):
                    yielded = True
                    yield None
                    return
                fd = private_open(path, os.O_RDONLY)
                try:
                    info = os.fstat(fd)
                    if (state.get("version") != 1 or state["size"] != info.st_size
                            or state["file"] != [info.st_dev, info.st_ino]
                            or os.pread(fd, 1, info.st_size - 1) != b"\n"):
                        raise ValueError("Storage inconsistency")
                finally:
                    os.close(fd)
                writer = Writer._resume_checkpoint(path, state["writer"])
                writer._adapter_state = state.get("adapter", {})
            except (ValueError, KeyError, TypeError, AttributeError, FileNotFoundError):
                seal(path, index, store, session, receipt, "Capture stopped after a storage inconsistency.")
                yielded = True
                yield None
                return
        else:
            header = {"ts": receipt, "agent": {"name": store.agent}, "sessionId": session,
                      "producer": {"name": "asr-hooks-" + store.agent, "version": "0.1.0", "method": "recorder", "source": store.source},
                      "missing": list(dict.fromkeys(MISSING + list(extra_missing) + ([] if store.full else ["content", "paths"]))), "extensions": [EXTENSION]}
            if start:
                header["startedAt"] = receipt
                if store.full and isinstance(cwd, str) and Path(cwd).is_absolute():
                    from agent_session_record.repository import repository_snapshot
                    header.update(repository_snapshot(cwd))
            changed = [False]
            _clean(parent, store.secrets, changed)
            if parent and not changed[0]:
                header["parent"] = {"session": reference(store.agent, parent), "kind": "subagent"}
            header = _clean(header, store.secrets, changed)
            if changed[0]:
                header["truncated"] = True
                header["missing"].append("redacted_content")
            writer = Writer(path, header)
            writer._adapter_state = {}
            if not start:
                writer.append({"type": "gap", "ts": receipt, "reason": "not_recorded", "detail": "Capture began without an explicit session start."})
        losses = [p for p in (marker, store.output / "capture.lost") if p.exists()]
        if losses:
            writer.append({"type": "gap", "ts": receipt, "reason": "not_recorded", "detail": "A callback could not be recorded."})
        yielded = True
        yield writer
        state = {"version": 1, "writer": writer._checkpoint(), "adapter": writer._adapter_state}
        if getattr(writer, "_capture_stopped", False) or path.stat().st_size >= MAX_STREAM - 4096 or len(json.dumps(state)) > MAX_STATE - 4096:
            if not getattr(writer, "_capture_stopped", False):
                writer.append({"type": "gap", "ts": receipt, "reason": "not_recorded", "detail": "Recorder storage limit reached. Capture stopped."})
            state = {"version": 1, "sealed": True}
        info = path.stat()
        state.update(size=info.st_size, file=[info.st_dev, info.st_ino])
        save(index, state)
        for loss in losses:
            loss.unlink(missing_ok=True)
    except Exception:
        # Never propagate recorder failure through an in-process callback.
        LOG.warning("ASR capture failed")
        mark_loss(store.output, marker.name if marker else "capture.lost")
        if writer is not None:
            try:
                writer.append({"type": "gap", "ts": receipt, "reason": "not_recorded", "detail": "A callback could not be recorded."})
            except Exception:
                pass
        if not yielded:
            yield None
    finally:
        if writer is not None:
            try:
                writer.close()
            except Exception:
                LOG.warning("ASR writer close failed")
        if lock is not None:
            os.close(lock)
