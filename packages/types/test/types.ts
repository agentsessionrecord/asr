import type { Annotation, ASRRecord, ConfiguredModelSettings, Discovery, Inference,
  Manifest, SessionInfo, TextPart, ToolResult } from "../src/index.js";

const cleared: ConfiguredModelSettings = null;
const info: SessionInfo = { type: "session_info", id: "info", agentSettings: {
  mode: null, externalSandbox: null, modelSettings: { temperature: null } }, tools: [] };
const inference: Inference = { type: "inference", id: "request", usage: { inputTokens: 0 } };
const result: ToolResult = { type: "tool_result", id: "result", status: "completed", input: null };
const annotation: Annotation = { type: "annotation", id: "title", session: "com.example.agent:run",
  kind: "title", at: "2026-10-31T12:00:00Z", source: { name: "example" }, data: { title: "Example" } };
const discovery: Discovery = { agent: "com.example.agent", supportsDeletionHook: false };
const manifest: Manifest = { $schema: "https://agentsessionrecord.org/schema/v0/manifest.schema.json",
  collector: { name: "example", version: "1.0" }, machine: "synthetic",
  window: { start: "2026-10-31T12:00:00Z", end: "2026-10-31T13:00:00Z" }, previousManifest: null, entries: [] };
const unknown: ASRRecord = { type: "future", id: "future", futureField: { value: "kept" } };
const part: TextPart = { type: "text", text: "exact\ntext" };
// @ts-expect-error Known content shapes require their recorded fields.
const badPart: TextPart = { type: "text" };
// @ts-expect-error A result requires a recorded status.
const badResult: ToolResult = { type: "tool_result", id: "result" };
// @ts-expect-error Inference settings cannot be cleared with null.
const badInference: Inference = { type: "inference", id: "request", settings: { temperature: null } };
void [cleared, info, inference, result, annotation, discovery, manifest, unknown, part, badPart, badResult, badInference];
