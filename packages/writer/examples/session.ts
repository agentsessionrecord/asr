import { Writer } from "@agent-session/writer";
const path = process.argv[2];
if (!path) throw new Error("Pass an output path");
const writer = new Writer(path, {
  agent: { name: "com.example.agent" },
  sessionId: "example-typescript",
  producer: { name: "example-writer", version: "1.0", method: "native" },
  missing: ["timestamps", "model"],
});
try {
  writer.update({ agentSettings: { mode: "ask", modelSettings: { reasoningEffort: "high" } } });
  writer.update({ tools: [{ name: "echo", inputSchema: { type: "object" } }] });
  writer.append({ type: "message", id: "prompt-1", role: "user", author: "human",
    content: [{ type: "text", text: "Echo the recorded native value." }] });
  writer.append({ type: "tool_call", callId: "9007199254740993", name: "echo",
    input: { nativeValue: 9007199254740993n } });
  writer.append({ type: "approval", callId: "9007199254740993",
    decision: "approved", by: "user", scope: "once" });
  writer.append({ type: "tool_result", callId: "9007199254740993", status: "completed",
    content: [{ type: "text", text: "9007199254740993" }] });
  writer.update({ agentSettings: { mode: null,
    modelSettings: { reasoningEffort: null } } });
  writer.update({ tools: [], missing: ["usage"] });
  writer.append({ type: "message", role: "assistant", phase: "final",
    content: [{ type: "text", text: "The value is stored as a string." }] });
  writer.append({ type: "inference" });
  writer.update({ title: "Echo a native value" });
} finally {
  writer.close();
}
