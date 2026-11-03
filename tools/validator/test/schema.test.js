import { test } from "node:test";
import assert from "node:assert/strict";
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import { isBase64 } from "../src/schema/base64.js";
import { readFileSync } from "node:fs";
import { validateRecord } from "../src/index.js";
import { AGENT_NAMES, buildSchemas, SCHEMA_FILES } from "../src/schema/build.js";
import { header, message, call, result, approval, change, vcs, inference, annotation, commit } from "./helpers.js";

const validRecords = [
  header(), { type: "session_info", id: "info", title: "" }, message(), call(), result(), approval(), change(), vcs(), inference(),
  { type: "gap", id: "gap", reason: "unknown" },
];
for (const record of validRecords) test(`${record.type} accepts its minimal shape and future fields`, () => {
  assert.deepEqual(validateRecord({ ...record, futureField: { preserved: true } }), []);
});

for (const [record, field, requirement] of [
  [header(), "type", "ASR-006"], [header(), "id", "ASR-006"], [header(), "agent", "ASR-019"],
  [header(), "producer", "ASR-019"], [header(), "sessionId", "ASR-019"], [header(), "formatVersion", "ASR-019"],
  [message(), "role", "ASR-021"], [message(), "content", "ASR-021"], [call(), "callId", "ASR-023"],
  [result(), "status", "ASR-025"], [change(), "path", "ASR-027"], [change(), "op", "ASR-027"], [change(), "status", "ASR-027"],
  [approval(), "decision", "ASR-073"],
  [vcs(), "action", "ASR-031"], [vcs(), "status", "ASR-031"], [vcs(), "evidence", "ASR-031"],
  [{ type: "gap", id: "gap", reason: "unknown" }, "reason", "ASR-039"],
]) test(`${record.type} requires ${field}`, () => {
  const copy = { ...record };
  delete copy[field];
  assert.ok(validateRecord(copy).some((problem) => problem.requirement === requirement && problem.code === "schema.required"));
});

const invalid = [
  ["unsupported version", header({ formatVersion: "0.2" }), "ASR-002"],
  ["agent without a name", header({ agent: {} }), "ASR-019"],
  ["producer without method", header({ producer: { name: "test", version: "1" } }), "ASR-019"],
  ["empty session identity", header({ sessionId: "" }), "ASR-010"],
  ["empty namespace", header({ namespace: "" }), "ASR-010"],
  ["unregistered short name", header({ agent: { name: "not-registered" } }), "ASR-010"],
  ["invalid reverse DNS name", header({ agent: { name: "com..agent" } }), "ASR-010"],
  ["relative cwd", header({ cwd: "work/app" }), "ASR-012"],
  ["invalid repository HEAD", header({ repos: [{ path: "/work", head: "abc" }] }), "ASR-031"],
  ["empty session_info", { type: "session_info", id: "info", future: 1 }, "ASR-020"],
  ["null session title", { type: "session_info", id: "info", title: null }, "ASR-020"],
  ["invalid includesSubagents", { type: "session_info", id: "info", usage: { includesSubagents: "false" } }, "ASR-020"],
  ["non-array content", message({ content: "text" }), "ASR-013"],
  ["part without type", message({ content: [{}] }), "ASR-013"],
  ["text without text", message({ content: [{ type: "text" }] }), "ASR-013"],
  ["image without media type", message({ content: [{ type: "image", data: "" }] }), "ASR-013"],
  ["audio with invalid base64", message({ content: [{ type: "audio", mimeType: "audio/wav", data: "?!" }] }), "ASR-013"],
  ["resource link without uri", message({ content: [{ type: "resource_link", name: "doc" }] }), "ASR-013"],
  ["resource without content", message({ content: [{ type: "resource", resource: { uri: "file:///a" } }] }), "ASR-013"],
  ["encrypted reasoning text", message({ content: [{ type: "reasoning", visibility: "encrypted", text: "" }] }), "ASR-015"],
  ["encrypted reasoning summary", message({ content: [{ type: "reasoning", visibility: "encrypted", summary: [] }] }), "ASR-015"],
  ["both tool input forms", call({ input: null, inputText: "null" }), "ASR-023"],
  ["zero-based location", call({ locations: [{ path: "file", line: 0 }] }), "ASR-023"],
  ["location without path", call({ locations: [{}] }), "ASR-023"],
  ["result subagent without session", result({ subagent: {} }), "ASR-025"],
  ["fractional exit code", result({ exec: { exitCode: 0.5 } }), "ASR-025"],
  ["relative process cwd", result({ exec: { cwd: "work" } }), "ASR-012"],
  ["nonstring command argument", result({ exec: { command: ["ls", 1] } }), "ASR-025"],
  ["negative duration", result({ durationMs: -1 }), "ASR-025"],
  ["move without oldPath", change({ op: "move" }), "ASR-027"],
  ["copy without oldPath", change({ op: "copy" }), "ASR-027"],
  ["both change forms", change({ patch: "", edits: [] }), "ASR-027"],
  ["file change call and actor", change({ callId: "c1", actor: "human" }), "ASR-027"],
  ["edit without newText", change({ edits: [{ oldText: "x" }] }), "ASR-027"],
  ["relative backslash path", change({ path: "src\\main.py" }), "ASR-012"],
  ["default file hash length", change({ after: { objectId: "a".repeat(64) } }), "ASR-030"],
  ["SHA256 file hash length", change({ before: { objectId: commit, objectIdType: "sha256" } }), "ASR-030"],
  ["uppercase file hash", change({ after: { objectId: "A".repeat(40) } }), "ASR-030"],
  ["invalid baseCommit", change({ baseCommit: "short" }), "ASR-031"],
  ["commit and prefix", vcs({ commit, commitPrefix: "aaaaaaa" }), "ASR-031"],
  ["vcs call and actor", vcs({ callId: "c1", actor: "external" }), "ASR-031"],
  ["uppercase commit", vcs({ commit: "A".repeat(40) }), "ASR-031"],
  ["commit with a trailing newline", vcs({ commit: commit + "\n" }), "ASR-031"],
  ["short prefix", vcs({ commitPrefix: "abcdef" }), "ASR-031"],
  ["full hash used as prefix", vcs({ commitPrefix: commit }), "ASR-031"],
  ["negative parentCount", vcs({ parentCount: -1 }), "ASR-031"],
  ["rewrite without endpoint", vcs({ rewrites: [{ from: commit }] }), "ASR-031"],
  ["PR without identity", vcs({ pr: { state: "open" } }), "ASR-031"],
  ["PR repository without number", vcs({ pr: { repository: "team/app" } }), "ASR-031"],
  ["PR malformed commit", vcs({ pr: { url: "https://example.com/pr/1", commits: ["short"] } }), "ASR-031"],
  ["model without id or request", inference({ model: { provider: "example" } }), "ASR-035"],
  ["negative input count", inference({ usage: { inputTokens: -1 } }), "ASR-036"],
  ["fractional output count", inference({ usage: { outputTokens: 1.5 } }), "ASR-036"],
  ["cost missing currency", inference({ cost: { amount: 0 } }), "ASR-037"],
  ["currency shape", inference({ cost: { amount: 1, currency: "usd" } }), "ASR-037"],
  ["gap count", { type: "gap", id: "gap", reason: "unknown", count: -1 }, "ASR-039"],
  ["parent kind missing", header({ parent: { session: "codex:parent" } }), "ASR-040"],
  ["empty copy source", message({ copiedFrom: {} }), "ASR-040"],
  ["metadata key", message({ _meta: { vendor: {} } }), "ASR-017"],
  ["vendor type grammar", { type: "vendor/event", id: "event" }, "ASR-017"],
  ["vendor content-part type grammar", message({ content: [{ type: "example/content" }] }), "ASR-017"],
  ["timestamp without zone", message({ ts: "2026-10-30T12:00:00" }), "ASR-006"],
  ["invalid calendar date", message({ ts: "2026-02-30T12:00:00Z" }), "ASR-006"],
];
for (const [name, record, requirement] of invalid) test(name, () => {
  assert.ok(validateRecord(record).some((problem) => problem.requirement === requirement), JSON.stringify(validateRecord(record)));
});

for (const id of ["", "a".repeat(257), "a\n", "a\u0000", "a\u007f", "a\u0085"]) test(`invalid record ID ${JSON.stringify(id.slice(0, 12))}`, () => {
  assert.ok(validateRecord(message({ id })).some((problem) => problem.requirement === "ASR-007"));
});
test("opaque IDs count Unicode characters and permit spaces and reserved punctuation", () => {
  for (const id of ["😀".repeat(256), "native:part#1 %", "☃"]) assert.deepEqual(validateRecord(message({ id })), []);
});

const refs = ["codex:run", "codex:install:run#record", "com.example.agent:run%3A7#prompt%201", "codex:a%25%23%00", "codex:雪#雪", "codex:%E9%9B%AA#%F0%9F%98%80", "codex:run#%3A%23%25"];
for (const session of refs) test(`valid reference ${session}`, () => assert.deepEqual(validateRecord(annotation({ session })), []));

test("session-only references reject fragments but preserve encoded hash characters", () => {
  const fields = (session) => [header({ parent: { session, kind: "fork" } }), message({ copiedFrom: { session, record: "r1" } }),
    message({ from: session }), call({ subagent: { session } }), result({ subagent: { session } })];
  for (const record of fields("codex:run#record")) assert.ok(validateRecord(record).some(({ requirement }) => requirement === "ASR-011"));
  for (const record of fields("codex:run%23record")) assert.deepEqual(validateRecord(record), []);
  assert.deepEqual(validateRecord(annotation({ session: "codex:run#record" })), []);
});

test("digit-leading reverse DNS labels work for agents, references, metadata and vendor types", () => {
  for (const name of ["com.1example", "org.37example.agent"]) {
    assert.deepEqual(validateRecord(header({ agent: { name } })), []);
    assert.deepEqual(validateRecord(message({ from: `${name}:run`, _meta: { [name]: {} } })), []);
    assert.deepEqual(validateRecord({ type: `${name}/event`, id: "v" }), []);
    assert.deepEqual(validateRecord(message({ content: [{ type: `${name}/content`, _meta: { [name]: { native: false } } }] })), []);
  }
});

test("vendor content parts share record naming while MCP metadata stays verbatim", () => {
  for (const type of ["example/content", "com..example/content", "com.example/", "com.example/a/b", "com.example/content\n"]) {
    for (const record of [message({ content: [{ type }] }), result({ content: [{ type }] })]) {
      assert.ok(validateRecord(record).some(({ requirement }) => requirement === "ASR-017"));
    }
  }
  const content = [
    { type: "com.example/content", _meta: { "com.example": { native: { type: "document" } } } },
    { type: "text", text: "known" },
    { type: "resource_link", uri: "https://example.com/notes", name: "notes", _meta: { audience: ["assistant"] } },
    { type: "resource", resource: { uri: "file:///notes", text: "notes" }, _meta: { priority: 0 } },
  ];
  const before = structuredClone(content);
  assert.deepEqual(validateRecord(message({ content })), []);
  assert.deepEqual(content, before);
});

test("VCS annotations enforce the exclusive call and actor forms", () => {
  assert.ok(validateRecord(annotation({ kind: "vcs", data: vcs({ callId: "c1", actor: "human" }) })).some(({ requirement }) => requirement === "ASR-031"));
});
for (const session of ["codex", "codex:", "codex::run", "codex:a:b:c", "codex:run#", "codex:a b", "codex:a%3a", "codex:a%", "codex:a%FF", "codex:%C0%80", "codex:%ED%A0%80", "codex:%F4%90%80%80", "codex:run#%00", "codex:run#%C2%80", "codex:run#" + "a".repeat(257), "codex:a#b#c"]) {
  test(`invalid reference ${session.slice(0, 40)}`, () => assert.ok(validateRecord(annotation({ session })).some((problem) => problem.requirement === "ASR-011")));
}

test("open enums, unknown parts and opaque fields are preserved without mutation", () => {
  const record = message({ role: "future_role", author: "_vendor", status: "future_status", content: [{ type: "future_part", opaque: { text: false } }], _meta: { "com.example.agent": { value: null } }, extra: 0 });
  const before = structuredClone(record);
  assert.deepEqual(validateRecord(record), []);
  assert.deepEqual(record, before);
  assert.deepEqual(validateRecord({ type: "com.example/event", id: "v", model: false, callId: 5 }), []);
  assert.deepEqual(validateRecord({ type: "future_core", id: "f" }), []);
  assert.deepEqual(validateRecord(change({ after: { objectIdType: "_future", objectId: "opaque" } })), []);
});

test("all agents in the local list and absolute path families are supported", () => {
  for (const name of AGENT_NAMES) assert.deepEqual(validateRecord(header({ agent: { name } })), []);
  for (const cwd of ["/work/app", "C:/work/app", "C:\\work\\app", "\\\\server\\share\\app"]) assert.deepEqual(validateRecord(header({ cwd })), []);
  assert.deepEqual(validateRecord(header({ repos: [{ path: "../other" }] })), []);
});

test("all content shapes, false values and optional unknown data remain intact", () => {
  const content = [
    { type: "text", text: " a\r\n", author: "human", origin: "prompt" },
    { type: "image", mimeType: "image/png" }, { type: "audio", mimeType: "audio/wav", data: "YQ==" },
    { type: "resource_link", uri: "https://example.com/a", name: "a" },
    { type: "resource", resource: { uri: "file:///a", text: "" } },
    { type: "resource", resource: { uri: "file:///b", blob: "" } },
    { type: "reasoning", visibility: "summary", summary: ["summary"] },
    { type: "reasoning", visibility: "encrypted" },
  ];
  assert.deepEqual(validateRecord(message({ content, truncated: false, ts: "2026-10-30T12:00:00.123456789+05:30" })), []);
  assert.deepEqual(validateRecord({ type: "session_info", id: "total", usage: { inputTokens: 0, includesSubagents: false }, cost: { amount: 0, currency: "USD" } }), []);
  assert.deepEqual(validateRecord(vcs({ commit: "a".repeat(64), parents: [], pr: { repository: "team/app", number: 1 } })), []);
});

for (const field of ["type", "id", "session", "kind", "at", "source", "data"]) test(`annotation requires ${field}`, () => {
  const record = annotation();
  delete record[field];
  assert.ok(validateRecord(record, "annotation").some((problem) => problem.code === "schema.required"));
});
for (const [kind, data] of [
  ["summary", { text: "Done", model: "example-model" }], ["outcome", { status: "_new", commit, revertedBy: commit }],
  ["test", { status: "passed", commit, name: "unit", url: "https://example.com/test" }],
  ["vcs", { action: "rebase", status: "completed", evidence: "observed" }], ["title", { title: "" }], ["future", [false, 0, null]],
]) test(`annotation kind ${kind}`, () => {
  assert.deepEqual(validateRecord(annotation({ kind, data })), []);
  if (kind !== "future") assert.ok(validateRecord(annotation({ kind, data: {} })).length > 0);
});

test("discovery matches the guide and stays open", () => {
  const record = { agent: "codex", namespace: "install", exportCommand: ["exporter", "sessions"], nativePaths: ["~/sessions/*"], formatVersions: ["0.1"], supportsDeletionHook: false, _meta: { "com.example.source": {} }, future: 0 };
  assert.deepEqual(validateRecord(record, "discovery"), []);
  assert.ok(validateRecord({ ...record, exportCommand: [] }, "discovery").length > 0);
  assert.ok(validateRecord({ ...record, supportsDeletionHook: "false" }, "discovery").length > 0);
});

test("published schemas compile together offline and match the generator", () => {
  const ajv = new Ajv2020({ strict: false });
  addFormats(ajv);
  ajv.addFormat("asr-base64", isBase64);
  const generated = buildSchemas();
  for (const [kind, filename] of Object.entries(SCHEMA_FILES)) {
    const schema = JSON.parse(readFileSync(new URL(`../../../schema/v0/${filename}`, import.meta.url), "utf8"));
    assert.deepEqual(schema, generated[kind]);
    ajv.addSchema(schema);
  }
  for (const schema of Object.values(generated)) assert.equal(typeof ajv.getSchema(schema.$id), "function");
});
