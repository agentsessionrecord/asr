import sys
from agent_session_record import Writer
from agent_session_record.models import Session, SessionAgent, SessionProducer
if len(sys.argv) != 2:
    raise SystemExit("Pass an output path")
header = Session(
    type="session", id="header", format_version="0.1",
    agent=SessionAgent(name="com.example.agent"),
    session_id="example-python",
    producer=SessionProducer(name="example-writer", version="1.0", method="native"),
    missing=["timestamps", "model"],
)
with Writer(sys.argv[1], header) as writer:
    writer.update({"agentSettings": {"mode": "ask",
        "modelSettings": {"reasoningEffort": "high"}}})
    writer.update({"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]})
    writer.append({"type": "message", "id": "prompt-1", "role": "user", "author": "human",
        "content": [{"type": "text", "text": "Echo the recorded native value."}]})
    writer.append({"type": "tool_call", "callId": "9007199254740993", "name": "echo",
        "input": {"nativeValue": 9007199254740993}})
    writer.append({"type": "approval", "callId": "9007199254740993",
        "decision": "approved", "by": "user", "scope": "once"})
    writer.append({"type": "tool_result", "callId": "9007199254740993", "status": "completed",
        "content": [{"type": "text", "text": "9007199254740993"}]})
    writer.update({"agentSettings": {"mode": None,
        "modelSettings": {"reasoningEffort": None}}})
    writer.update({"tools": [], "missing": ["usage"]})
    writer.append({"type": "message", "role": "assistant", "phase": "final",
        "content": [{"type": "text", "text": "The value is stored as a string."}]})
    writer.append({"type": "inference"})
