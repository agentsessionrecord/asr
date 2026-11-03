"""Write completed ASR session events in caller order without rewriting lines."""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
from importlib.resources import files
import json
import math
import os
import stat
from pathlib import Path
from threading import RLock
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel
from referencing import Registry, Resource

MAX_SAFE_INTEGER = 2**53 - 1


def derive_id(scope: str, record_type: str, position: int, collision: int = 0) -> str:
    """Derive the same opaque ID as the TypeScript writer for a source position."""
    if any(type(value) is not int or not 0 <= value <= MAX_SAFE_INTEGER for value in (position, collision)):
        raise ValueError("ID positions must be non-negative safe integers")
    data = json.dumps([scope, record_type, position, collision], ensure_ascii=False, separators=(",", ":"))
    return "asr-" + hashlib.sha256(data.encode("utf-8")).hexdigest()


def _json_value(value: Any, seen: set[int] | None = None) -> Any:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python", by_alias=True, exclude_unset=True)
    if value is None or type(value) in (str, bool):
        return value
    if type(value) is int:
        return str(value) if abs(value) > MAX_SAFE_INTEGER else value
    if type(value) is float:
        if not math.isfinite(value) or abs(value) > MAX_SAFE_INTEGER:
            raise ValueError("Use strings for large native values and finite numbers otherwise")
        return value
    seen = set() if seen is None else seen
    if id(value) in seen:
        raise ValueError("Expected acyclic JSON data")
    seen.add(id(value))
    try:
        if isinstance(value, Mapping):
            if any(type(key) is not str for key in value):
                raise TypeError("JSON object keys must be strings")
            return {key: _json_value(item, seen) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_json_value(item, seen) for item in value]
        raise TypeError("Expected JSON data or a generated model")
    finally:
        seen.remove(id(value))


def _validator() -> Draft202012Validator:
    documents = [json.loads(path.read_text(encoding="utf-8")) for path in files(__package__).joinpath("_schemas").iterdir() if path.name.endswith(".json")]
    registry = Registry().with_resources((doc["$id"], Resource.from_contents(doc)) for doc in documents)
    checker = FormatChecker()

    @checker.checks("asr-base64")
    def is_base64(value: Any) -> bool:
        if not isinstance(value, str):
            return True
        # The ASR shape accepts empty content and does not constrain padding bits.
        if len(value) % 4:
            return False
        end = len(value)
        if end and value[end - 1] == "=":
            end -= 1
        if end and value[end - 1] == "=":
            end -= 1
        return all("A" <= char <= "Z" or "a" <= char <= "z" or "0" <= char <= "9" or char in "+/" for char in value[:end])

    core = next(doc for doc in documents if doc["$id"].endswith("/agent-session.schema.json"))
    return Draft202012Validator(core, registry=registry, format_checker=checker)


_VALIDATOR = _validator()


def _check_vcs(record: dict[str, Any]) -> None:
    if "parents" in record and "parentCount" in record and len(record["parents"]) != record["parentCount"]:
        raise ValueError("Parent count must match parents")
    pairs = record.get("rewrites", [])
    pr = record.get("pr", {})
    commits = [record.get(key) for key in ("commit", "headBefore", "headAfter")]
    commits += record.get("parents", []) + [value for pair in pairs for value in (pair["from"], pair["to"])]
    commits += [pr.get("headCommit"), pr.get("mergeCommit")] + pr.get("commits", [])
    if len({len(value) for value in commits if isinstance(value, str)}) > 1:
        raise ValueError("Full commit IDs must have the same length")
    if any(pair["from"] == pair["to"] for pair in pairs):
        raise ValueError("Rewrite endpoints must differ")


class Writer:
    """Create a new private stream. Calls append synchronously in receipt order."""

    def __init__(self, path: str | Path, header: BaseModel | Mapping[str, Any]):
        self._lock = RLock()
        self._fd: int | None = None
        self._failed = False
        self._ids: set[str] = set()
        self._results: set[str] = set()
        self._missing: set[str] = set()
        self._position = 0
        value = _json_value(header)
        if not isinstance(value, dict):
            raise TypeError("Expected a session header object")
        if value.get("type", "session") != "session" or value.get("formatVersion", "0.1") != "0.1":
            raise ValueError("A writer requires a version 0.1 session header")
        agent = value.get("agent")
        agent_name = agent.get("name") if isinstance(agent, dict) else None
        self._scope = json.dumps([agent_name, value.get("namespace"), value.get("sessionId")], ensure_ascii=False, separators=(",", ":"))
        record = self._prepare({**value, "type": "session", "formatVersion": "0.1"})
        self._copied_through = record.get("parent", {}).get("copiedThrough")
        if self._copied_through == record["id"]:
            raise ValueError("Copied prefix must end after the header")
        self._fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            self._write(record)
        except BaseException:
            os.close(self._fd)
            self._fd = None
            raise

    def _prepare(self, value: dict[str, Any]) -> dict[str, Any]:
        if "id" not in value:
            collision = 0
            while True:
                value["id"] = derive_id(self._scope, value.get("type"), self._position, collision)
                if value["id"] not in self._ids:
                    break
                collision += 1
        error = next(_VALIDATOR.iter_errors(value), None)
        if error is not None:
            pointer = "/" + "/".join(map(str, error.absolute_path))
            raise ValueError(f"Record fails schema at {pointer}")
        if value["id"] in self._ids:
            raise ValueError("Duplicate record ID")
        if value["type"] == "tool_result" and value.get("callId") in self._results:
            raise ValueError("Duplicate result callId")
        if value["type"] == "inference" and "model" not in value and "model" not in self._missing:
            raise ValueError("Declare model in missing before an inference without a model")
        if value["type"] == "vcs":
            _check_vcs(value)
        if value["type"] == "approval":
            if value["decision"] == "cancelled" and ("scope" in value or "person" in value):
                raise ValueError("Cancelled approvals have no scope or person")
            if "person" in value and "by" in value and value["by"] != "user":
                raise ValueError("A recorded person answers by user")
        return value

    @property
    def position(self) -> int:
        """Number of completed records, including the session header."""
        return self._position

    @classmethod
    def _resume_checkpoint(cls, path, state):
        """Internal fast path for a producer's locked, private index sidecar.

        The producer must verify the file identity and byte length first. This
        checkpoint is never accepted from ASR or untrusted request content.
        """
        if (type(state.get("position")) is not int or state["position"] < 1
                or not isinstance(state.get("scope"), str)
                or any(not isinstance(state.get(key), list) or
                       any(not isinstance(item, str) for item in state[key])
                       for key in ("ids", "results", "missing"))
                or len(set(state["ids"])) != state["position"]):
            raise ValueError("Invalid writer checkpoint")
        self = cls.__new__(cls)
        self._lock = RLock()
        self._failed = False
        self._position = state["position"]
        self._scope = state["scope"]
        self._ids = set(state["ids"])
        self._results = set(state["results"])
        self._missing = set(state["missing"])
        self._copied_through = state.get("copiedThrough")
        self._fd = os.open(path, os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0))
        return self

    def _checkpoint(self):
        return {"position": self._position, "scope": self._scope,
                "ids": sorted(self._ids), "results": sorted(self._results),
                "missing": sorted(self._missing), "copiedThrough": self._copied_through}

    @classmethod
    def resume(cls, path: str | Path, *, max_bytes: int = 8 * 1024 * 1024) -> Writer:
        """Reopen a complete stream without changing its prefix.

        The caller must serialize other processes for the lifetime of this writer.
        Incomplete or invalid streams are left untouched. The size bound keeps
        short-lived hook processes from reading an unbounded history.
        """
        fd = os.open(path, os.O_RDWR | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0))
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
                raise ValueError("Expected a bounded regular stream")
            with os.fdopen(os.dup(fd), "rb") as stream:
                data = stream.read(max_bytes + 1)
            if not data or len(data) > max_bytes or not data.endswith(b"\n"):
                raise ValueError("Expected a complete bounded stream")

            def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
                result: dict[str, Any] = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("Duplicate JSON key")
                    result[key] = value
                return result

            def reject_constant(value: str) -> None:
                raise ValueError("Non-finite JSON number")

            def safe_integer(value: str) -> int:
                number = int(value)
                if abs(number) > MAX_SAFE_INTEGER:
                    raise ValueError("Expected safe JSON numbers")
                return number

            def safe_float(value: str) -> float:
                number = float(value)
                if not math.isfinite(number) or abs(number) > MAX_SAFE_INTEGER:
                    raise ValueError("Expected finite safe JSON numbers")
                return number

            records = [json.loads(line, object_pairs_hook=unique_object, parse_constant=reject_constant,
                                  parse_int=safe_integer, parse_float=safe_float)
                       for line in data.decode("utf-8").split("\n")[:-1]]
            header = records[0]
            if not isinstance(header, dict) or header.get("type") != "session" or header.get("formatVersion") != "0.1":
                raise ValueError("Expected a version 0.1 session header")
            self = cls.__new__(cls)
            self._lock = RLock()
            self._fd = None
            self._failed = False
            self._ids = set()
            self._results = set()
            self._missing = set()
            self._position = 0
            self._scope = json.dumps([header.get("agent", {}).get("name"), header.get("namespace"), header.get("sessionId")], ensure_ascii=False, separators=(",", ":"))
            self._copied_through = header.get("parent", {}).get("copiedThrough")
            for position, record in enumerate(records):
                if not isinstance(record, dict) or "id" not in record or record.get("type") == "annotation" or (position and record.get("type") == "session"):
                    raise ValueError("Expected session records with IDs")
                self._remember(self._prepare(record))
            if self._copied_through and (self._copied_through == header["id"] or self._copied_through not in self._ids):
                raise ValueError("Invalid copied prefix")
            self._fd = fd
            return self
        except BaseException:
            os.close(fd)
            raise

    def _remember(self, record: dict[str, Any]) -> str:
        self._position += 1
        self._ids.add(record["id"])
        if record["type"] == "tool_result" and "callId" in record:
            self._results.add(record["callId"])
        if record["type"] in ("session", "session_info"):
            self._missing.update(record.get("missing", []))
        return record["id"]

    def _write(self, record: dict[str, Any]) -> str:
        data = (json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            remaining = memoryview(data)
            while remaining:
                count = os.write(self._fd, remaining)
                if count <= 0:
                    raise OSError("Write made no progress")
                remaining = remaining[count:]
        except BaseException:
            self._failed = True
            raise
        return self._remember(record)

    def append(self, record: BaseModel | Mapping[str, Any]) -> str:
        with self._lock:
            if self._fd is None or self._failed:
                raise ValueError("Writer is closed or failed")
            value = _json_value(record)
            if not isinstance(value, dict):
                raise TypeError("Expected a record object")
            if value.get("type") in ("session", "annotation"):
                raise ValueError("Append session events only. Annotations require a separate file")
            return self._write(self._prepare(value))

    def update(self, fields: Mapping[str, Any]) -> str:
        if "type" in fields:
            raise ValueError("update supplies the session_info type")
        return self.append({**fields, "type": "session_info"})

    def close(self) -> None:
        with self._lock:
            if self._fd is None:
                return
            os.close(self._fd)
            self._fd = None
            if self._copied_through and self._copied_through not in self._ids:
                raise ValueError("Copied prefix must end at a record after the header")

    def __enter__(self) -> Writer:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
