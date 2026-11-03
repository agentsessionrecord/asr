import json

import pytest

from agent_session_record import Writer
from agent_session_record.content import content_part


@pytest.mark.parametrize("kind", ["document", "_vendor", "example/content", "com.example/content"])
def test_native_parts_use_one_wrapper_beside_known_text(kind, tmp_path):
    native = {"type": kind, "name": "notes.pdf", "empty": False}
    text = {"type": "text", "text": "known"}
    content = [content_part(native), content_part(text)]
    assert content == [
        {"type": "org.agentsessionrecord.native/content",
         "_meta": {"org.agentsessionrecord.native": {"native": native}}}, text]
    path = tmp_path / "parts.jsonl"
    with Writer(path, {"agent": {"name": "com.example.agent"}, "sessionId": "synthetic",
                       "producer": {"name": "test", "version": "1", "method": "recorder"}}) as writer:
        writer.append({"type": "message", "role": "user", "content": content})
    assert json.loads(path.read_text().splitlines()[1])["content"] == content


def test_core_resource_metadata_is_preserved():
    resource = {"type": "resource_link", "uri": "https://example.com/notes", "name": "notes",
                "_meta": {"audience": ["assistant"]}}
    assert content_part(resource) == resource


def test_reasoning_representation_is_not_invented():
    from agent_session_record.content import content_part, reasoning_part
    assert content_part({"type": "thinking", "thinking": "", "signature": "opaque"}) == {"type": "reasoning", "visibility": "omitted"}
    assert content_part({"type": "thinking", "thinking": "summary", "signature": "opaque"}) == {"type": "reasoning", "visibility": "summary", "summary": ["summary"]}
    assert reasoning_part(summary=[""]) == {"type": "reasoning", "visibility": "omitted"}
    assert reasoning_part(text="visible") == {"type": "reasoning", "text": "visible"}
    assert reasoning_part(text="visible", visibility="full")["visibility"] == "full"
    assert reasoning_part(text="secret", summary=["secret"], visibility="encrypted") == {"type": "reasoning", "visibility": "encrypted"}
