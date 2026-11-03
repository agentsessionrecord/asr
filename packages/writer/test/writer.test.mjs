import assert from "node:assert/strict";
import fs from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import { mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import { afterEach, beforeEach, test } from "node:test";
import { validateFile } from "@agent-session/validate";
import { Writer, deriveId } from "../dist/index.js";

let directory;
beforeEach(() => { directory = mkdtempSync(join(tmpdir(), "asr-writer-ts-")); });
afterEach(() => {
  try {
    for (const name of readdirSync(directory).filter((name) => name.endsWith(".jsonl"))) {
      const result = validateFile(join(directory, name));
      assert.equal(result.valid, true, JSON.stringify(result.diagnostics));
      assert.equal(result.diagnostics.length, 0, JSON.stringify(result.diagnostics));
    }
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
const header = (extra = {}) => ({
  agent: { name: "com.example.agent" }, sessionId: "synthetic",
  producer: { name: "writer-test", version: "1.0", method: "native" }, ...extra,
});
const rows = (path) => readFileSync(path, "utf8").trimEnd().split("\n").map(JSON.parse);
const message = (extra = {}) => ({ type: "message", role: "user", content: [], ...extra });

test("the 30-line example produces a valid stream", () => {
  const example = new URL("../examples/session.ts", import.meta.url);
  assert.equal(readFileSync(example, "utf8").trimEnd().split("\n").length, 30);
  execFileSync(process.execPath, ["--experimental-strip-types", example.pathname, join(directory, "example.jsonl")], { stdio: "pipe" });
});

test("append keeps complete byte prefixes, exact text, and private file permissions", () => {
  const path = join(directory, "append.jsonl");
  const writer = new Writer(path, header());
  const first = readFileSync(path);
  const content = [{ type: "text", text: "  café\n\r\n😀\t" }];
  writer.append(message({ id: "native-id", content }));
  content[0].text = "changed by caller";
  assert.deepEqual(readFileSync(path).subarray(0, first.length), first);
  assert.equal(rows(path)[1].content[0].text, "  café\n\r\n😀\t");
  assert.equal(rows(path)[1].id, "native-id");
  assert.equal(statSync(path).mode & 0o777, 0o600);
  assert.throws(() => new Writer(path, header()), /EEXIST/);
  writer.close();
  writer.close();
  assert.throws(() => writer.append(message()), /closed/);
});

test("settings, tools, approvals, and losses stay at their source positions", () => {
  const path = join(directory, "settings.jsonl");
  const writer = new Writer(path, header({ missing: ["timestamps"] }));
  const initial = { agentSettings: { mode: "ask", approval: false, sandbox: { enabled: false },
    asks: "sometimes", modelSettings: { temperature: 0, reasoningEffort: "high" },
    externalSandbox: { kind: "container", source: "setting", native: { id: 9007199254740993n } } },
    tools: [{ name: "echo", inputSchema: { type: "object" } }] };
  writer.update(initial);
  writer.update({ agentSettings: { mode: "" } });
  writer.update({ agentSettings: { modelSettings: { reasoningEffort: null } } });
  writer.update({ agentSettings: { externalSandbox: {}, modelSettings: null } });
  writer.append({ type: "tool_call", id: "call", callId: "c", name: "echo", input: { value: "requested" } });
  writer.append(message({ id: "notice", content: [{ type: "text", text: "Between call and result" }] }));
  writer.append({ type: "approval", callId: "c", decision: "approved", by: "policy", native: { value: 9007199254740993n } });
  writer.append({ type: "tool_result", callId: "c", status: "completed", input: null });
  writer.update({ agentSettings: { mode: null, externalSandbox: null }, tools: [], missing: ["usage", "model"] });
  writer.update({ missing: [] });
  writer.append({ type: "inference", usage: { inputTokens: 0 } });
  writer.close();
  const records = rows(path);
  assert.deepEqual(records[2].agentSettings, { mode: "" });
  assert.deepEqual(records[3].agentSettings, { modelSettings: { reasoningEffort: null } });
  assert.deepEqual(records[4].agentSettings, { externalSandbox: {}, modelSettings: null });
  assert.deepEqual(records.slice(5, 9).map((row) => row.type), ["tool_call", "message", "approval", "tool_result"]);
  assert.equal(records[7].native.value, "9007199254740993");
  assert.equal(records[8].input, null);
  assert.deepEqual(records[9].tools, []);
  assert.deepEqual(records[10].missing, []);
  assert.equal(records.some((row) => "ts" in row || "endedAt" in row), false);
});

test("schema failures, duplicate IDs and duplicate results leave bytes and ID positions untouched", () => {
  const path = join(directory, "rejections.jsonl");
  const writer = new Writer(path, header());
  writer.append({ type: "tool_call", id: "call", callId: "c", name: "echo" });
  writer.append({ type: "tool_result", id: "result", callId: "c", status: "completed" });
  const before = readFileSync(path);
  const circular = {}; circular.self = circular;
  for (const record of [message({ id: "call" }), { type: "tool_result", callId: "c", status: "completed" },
    { type: "tool_result", status: "completed", input: null, inputText: "" },
    { type: "tool_call", callId: "bad", input: null, inputText: "" },
    { type: "approval", subject: "host", decision: "cancelled", scope: "once" },
    { type: "approval", subject: "host", decision: "approved", by: "policy", person: { name: "Example" } },
    { type: "session_info" }, { type: "inference" }, { type: "session" }, { type: "annotation" },
    { type: "message", role: "user" }, message({ id: "bad\nID" }),
    message({ value: Number.NaN }), message({ value: Infinity }), message({ value: 2 ** 53 }),
    message({ value: undefined }), message({ value: new Date() }), message({ value: circular }),
    { type: "inference", model: { id: "m" }, usage: { inputTokens: 9007199254740993n } },
    { type: "vcs", action: "commit", status: "completed", evidence: "observed", parents: [], parentCount: 1 },
    { type: "vcs", action: "rebase", status: "completed", evidence: "observed", rewrites: [{ from: "a".repeat(40), to: "a".repeat(40) }] },
    { type: "vcs", action: "merge", status: "completed", evidence: "observed", commit: "a".repeat(40), parents: ["b".repeat(64)] },
    { type: "file_change", path: "a", op: "move", status: "applied" },
    message({ content: [{ type: "reasoning", visibility: "encrypted", text: "forbidden" }] })]) {
    assert.throws(() => writer.append(record));
    assert.deepEqual(readFileSync(path), before);
  }
  assert.throws(() => writer.update({ type: "message" }));
  writer.append(message());
  writer.close();
  const expected = new Writer(join(directory, "expected.jsonl"), header());
  expected.append({ type: "tool_call", id: "call", callId: "c", name: "echo" });
  expected.append({ type: "tool_result", id: "result", callId: "c", status: "completed" });
  expected.append(message()); expected.close();
  assert.deepEqual(readFileSync(path), readFileSync(join(directory, "expected.jsonl")));
});

test("all core records and unknown data survive", () => {
  const path = join(directory, "core.jsonl");
  const writer = new Writer(path, header({ parent: { session: "com.example.agent:parent", kind: "fork", copiedThrough: "copy" } }));
  writer.append(message({ id: "copy", role: "_custom", unknown: { number: 9007199254740993n }, content: [{ type: "future", value: false }] }));
  writer.append({ type: "inference", id: "i", model: { requested: "alias" }, cost: { amount: 0, currency: "USD" } });
  writer.append({ type: "file_change", path: "src/main.py", op: "modify", status: "applied", actor: "harness", edits: [{ oldText: "", newText: "print(1)\n" }] });
  writer.append({ type: "vcs", action: "commit", status: "completed", evidence: "observed", actor: "harness", commit: "a".repeat(40), parents: [], parentCount: 0 });
  writer.append({ type: "gap", reason: "not_retained", count: 0 });
  writer.close();
  assert.equal(rows(path)[1].unknown.number, "9007199254740993");
  assert.deepEqual(rows(path)[1].content, [{ type: "future", value: false }]);
});

test("ordering and unique IDs hold across 24 deterministic event sequences", () => {
  for (let seed = 1; seed <= 24; seed++) {
    let state = seed;
    const random = () => (state = (Math.imul(state, 1664525) + 1013904223) >>> 0);
    const path = join(directory, `property-${seed}.jsonl`);
    const writer = new Writer(path, header());
    const expected = [];
    for (let index = 0; index < 80; index++) {
      const text = `${random()}:\nλ😀`;
      expected.push(text);
      writer.append(message({ ...(index % 3 ? {} : { id: `native-${index}` }),
        ts: `2026-10-31T12:00:${String(random() % 60).padStart(2, "0")}Z`, content: [{ type: "text", text }] }));
    }
    writer.close();
    const records = rows(path);
    assert.deepEqual(records.slice(1).map((record) => record.content[0].text), expected);
    assert.equal(new Set(records.map((record) => record.id)).size, records.length);
    assert.deepEqual(Object.keys(records[1]).includes("ts"), true);
  }
});

test("derived IDs are stable across languages and handle explicit ID collisions", () => {
  const vectors = JSON.parse(readFileSync(new URL("../../types/test/id-vectors.json", import.meta.url), "utf8"));
  for (const vector of vectors) assert.equal(deriveId(...vector.args), vector.id);
  assert.throws(() => deriveId("scope", "message", -1));
  const scope = JSON.stringify(["com.example.agent", null, "synthetic"]);
  const path = join(directory, "collision.jsonl");
  const writer = new Writer(path, header({ id: deriveId(scope, "message", 1) }));
  const id = writer.append(message()); writer.close();
  assert.equal(id, deriveId(scope, "message", 1, 1));
});

test("partial writes finish the line and I/O failures stop further appends", () => {
  const path = join(directory, "partial.jsonl");
  const writer = new Writer(path, header());
  const original = fs.writeSync;
  try {
    fs.writeSync = (fd, bytes, offset, length) => original(fd, bytes, offset, Math.min(length, 3));
    syncBuiltinESMExports();
    writer.append(message({ content: [{ type: "text", text: "😀😀😀" }] }));
    const before = readFileSync(path);
    fs.writeSync = () => { throw new Error("synthetic disk failure"); };
    syncBuiltinESMExports();
    assert.throws(() => writer.append(message()), /disk failure/);
    assert.throws(() => writer.append(message()), /failed/);
    assert.deepEqual(readFileSync(path), before);
  } finally {
    fs.writeSync = original;
    syncBuiltinESMExports();
    writer.close();
  }
});


test("oversized core counts can be preserved as metadata with a declared loss", () => {
  const path = join(directory, "large-count.jsonl");
  const writer = new Writer(path, header({ missing: ["usage"] }));
  writer.append({ type: "inference", model: { id: "example-model" },
    usage: { outputTokens: Number.MAX_SAFE_INTEGER, reasoningTokens: 0 },
    _meta: { "com.example.agent": { inputTokens: 9007199254740993n } } });
  writer.append({ type: "tool_call", callId: "large-input", name: "echo",
    input: { nativeId: 9007199254740993n } });
  writer.append({ type: "tool_result", callId: "large-input", status: "completed" });
  writer.close();
  const records = rows(path);
  assert.deepEqual(records[0].missing, ["usage"]);
  assert.equal("inputTokens" in records[1].usage, false);
  assert.equal(records[1].usage.outputTokens, Number.MAX_SAFE_INTEGER);
  assert.equal(records[1].usage.reasoningTokens, 0);
  assert.equal(records[1]._meta["com.example.agent"].inputTokens, "9007199254740993");
  assert.equal(records[2].input.nativeId, "9007199254740993");
});


test("approval decisions can omit both call and subject", () => {
  const path = join(directory, "unlinked-approval.jsonl");
  const writer = new Writer(path, header());
  for (const decision of ["approved", "denied", "cancelled"]) writer.append({ type: "approval", decision });
  writer.close();
  assert.ok(rows(path).slice(1).every(row => !("callId" in row) && !("subject" in row)));
});
