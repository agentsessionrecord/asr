import json
from pathlib import Path

import pytest

from agent_session_record import Writer

HEADER = {"sessionId": "synthetic-session", "agent": {"name": "hermes"}, "producer": {"name": "synthetic", "version": "1", "method": "recorder"}}


def test_resume_preserves_prefix_ids_and_one_result(tmp_path):
    path = tmp_path / "session.jsonl"
    with Writer(path, HEADER) as writer:
        writer.append({"type": "tool_call", "callId": "synthetic-call", "name": "terminal"})
    prefix = path.read_bytes()
    with Writer.resume(path) as writer:
        assert writer.position == 2
        writer.append({"type": "tool_result", "callId": "synthetic-call", "status": "completed"})
    assert path.read_bytes().startswith(prefix)
    with Writer.resume(path) as writer:
        with pytest.raises(ValueError, match="Duplicate result"):
            writer.append({"type": "tool_result", "callId": "synthetic-call", "status": "completed"})
    assert len({json.loads(line)["id"] for line in path.read_text().splitlines()}) == 3


@pytest.mark.parametrize("tail", [
    b'{"type":', b'\n', b'{"id":"a","id":"b"}\n', b'{"type":"session","id":"another"}\n',
    b'{"type":"synthetic.example/event","id":"a","value":NaN}\n',
    b'{"type":"synthetic.example/event","id":"a","value":1e999}\n',
    b'{"type":"synthetic.example/event","id":"a","value":9007199254740992}\n',
])
def test_resume_rejects_corruption_without_repairing_it(tail, tmp_path):
    path = tmp_path / "corrupted.txt"
    with Writer(path, HEADER):
        pass
    with path.open("ab") as stream:
        stream.write(tail)
    before = path.read_bytes()
    with pytest.raises((ValueError, json.JSONDecodeError)):
        Writer.resume(path)
    assert path.read_bytes() == before


def test_resume_accepts_unicode_line_separators_inside_json_strings(tmp_path):
    path = tmp_path / "session.jsonl"
    with Writer(path, HEADER) as writer:
        writer.append({"type": "message", "role": "user", "content": [{"type": "text", "text": "synthetic\u2028text\u2029"}]})
    prefix = path.read_bytes()
    with Writer.resume(path) as writer:
        writer.append({"type": "gap", "reason": "not_recorded"})
    assert path.read_bytes().startswith(prefix)
    assert len(path.read_bytes().split(b"\n")) == 4


def test_resume_size_bound_and_symlink(tmp_path):
    path = tmp_path / "session.jsonl"
    with Writer(path, HEADER):
        pass
    with pytest.raises(ValueError, match="bounded"):
        Writer.resume(path, max_bytes=1)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(OSError):
        Writer.resume(link)
