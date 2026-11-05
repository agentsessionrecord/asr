import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { validate, validateRecord, validateManifest } from "../src/index.js";
import { checkBlock } from "../scripts/check-doc-examples.mjs";
import { header, message, call, result, approval, lines, temporaryDirectory } from "./helpers.js";

const info = (agentSettings) => ({ type: "session_info", id: "settings", agentSettings });
const read = (name) => readFileSync(new URL(`../../../examples/${name}`, import.meta.url));
const manifest = () => JSON.parse(read("collection.manifest.json"));
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");

test("all three identity positions use the same sourced identity shape", () => {
  const positions = (person) => [header({ user: person }), message({ person }), approval({ by: "user", person })];
  for (const field of ["id", "email", "name"]) {
    for (const record of positions({ [field]: "identity", source: "_future", future: true })) assert.deepEqual(validateRecord(record), []);
    for (const record of positions({ id: "identity", [field]: "" })) assert.ok(validateRecord(record).some(({ requirement }) => requirement === "ASR-019"));
  }
  for (const person of [{}, { source: "configured" }, null, [], "someone", { id: 7 }, { name: "A", source: false }]) {
    for (const record of positions(person)) assert.ok(validateRecord(record).some(({ requirement }) => requirement === "ASR-019"));
  }
});

test("approval records preserve source order, open values and any native JSON", () => {
  const decisions = [];
  for (const decision of ["approved", "denied", "cancelled", "future", "_vendor"]) {
    for (const by of ["user", "policy", "mode", "hook", "classifier", "fallback", "future"]) {
      for (const scope of ["once", "session", "always", "future"]) {
        for (const native of [null, false, 0, "", [], { decision: "original" }]) {
          decisions.push(approval({ id: `approval-${decisions.length}`, decision, by, ...(decision === "cancelled" ? {} : { scope }), native }));
        }
      }
    }
  }
  const stream = lines(header(), call(), ...decisions, result());
  const checked = validate(stream);
  assert.deepEqual(checked.diagnostics, []);
  assert.deepEqual(checked.records.filter(({ value }) => value.type === "approval").map(({ value }) => value), decisions);
  assert.deepEqual(validateRecord({ type: "approval", id: "minimal", decision: "approved" }), []);
  for (const fields of [{ decision: undefined }, { decision: 1 }, { by: false }, { scope: false }, { subject: [] }, { callId: null }]) {
    const record = JSON.parse(JSON.stringify(approval(fields)));
    assert.ok(validateRecord(record).some(({ requirement }) => requirement === "ASR-073"));
  }
});

test("approvals survive disconnects and can straddle a settings change", () => {
  const first = approval({ ts: "2026-10-30T18:00:00Z", by: "user", scope: "once" });
  const disconnected = validate(lines(header(), call(), first));
  assert.equal(disconnected.valid, true);
  assert.deepEqual(disconnected.diagnostics.map(({ code }) => code), ["call-without-result"]);
  assert.deepEqual(disconnected.records.at(-1).value, first);
  const change = info({ approval: "on-request", asks: "sometimes" });
  const second = approval({ id: "second", ts: "2026-10-30T18:00:02Z", subject: "sandbox-escape", by: "user" });
  const checked = validate(lines(header(), call(), first, change, second, result()));
  assert.deepEqual(checked.diagnostics, []);
  assert.deepEqual(checked.records.slice(2, 5).map(({ value }) => value), [first, change, second]);
});

test("approvals without calls use subjects and unresolved or ambiguous call links warn", () => {
  const grant = approval({ callId: undefined, subject: "packages.example.com", scope: "session" });
  assert.deepEqual(validate(lines(header(), grant)).diagnostics, []);
  const unmatched = validate(lines(header(), approval()));
  assert.equal(unmatched.valid, true);
  assert.deepEqual(unmatched.diagnostics.map(({ requirement, code, pointer }) => ({ requirement, code, pointer })), [
    { requirement: "ASR-070", code: "unpaired-approval", pointer: "/callId" },
  ]);
  assert.deepEqual(validate(lines(header(), approval(), call(), result())).diagnostics, []);
  assert.ok(validate(lines(header(), call(), call({ id: "second" }), approval())).diagnostics.some(({ code }) => code === "unpaired-approval"));
});

test("a result names the approval it followed, which must be local and for the same call", () => {
  const command = approval({ id: "command", by: "user", scope: "once" });
  const escape = approval({ id: "escape", decision: "denied", subject: "sandbox-escape" });
  const grant = approval({ id: "grant", callId: undefined, subject: "packages.example.com" });
  const problems = (output) => output.diagnostics.map(({ severity, requirement, code, line, pointer }) => ({ severity, requirement, code, line, pointer }));
  for (const records of [
    [call(), command, escape, result({ approvalId: "command" })],
    [call(), command, escape, result({ status: "denied", approvalId: "escape" })],
    [call(), result({ approvalId: "command" }), command],
    [call(), grant, result({ approvalId: "grant" })],
    [call(), command, result()],
  ]) assert.deepEqual(validate(lines(header(), ...records)).diagnostics, []);
  const dangling = validate(lines(header(), call(), command, message({ id: "note" }), result({ approvalId: "note" })));
  assert.equal(dangling.valid, false);
  assert.deepEqual(problems(dangling), [{ severity: "error", requirement: "ASR-079", code: "unresolved-approval", line: 5, pointer: "/approvalId" }]);
  const other = approval({ id: "other", callId: "c2" });
  const mismatch = validate(lines(header(), call(), call({ id: "call-2", callId: "c2" }), other, result({ approvalId: "other" }), result({ id: "result-2", callId: "c2" })));
  assert.deepEqual(problems(mismatch), [{ severity: "error", requirement: "ASR-079", code: "approval-call-mismatch", line: 5, pointer: "/approvalId" }]);
  const unlinked = result({ approvalId: "command" });
  delete unlinked.callId;
  assert.deepEqual(problems(validate(lines(header(), call(), command, unlinked))).filter(({ severity }) => severity === "error"),
    [{ severity: "error", requirement: "ASR-079", code: "approval-call-mismatch", line: 4, pointer: "/approvalId" }]);
  assert.deepEqual(validateRecord(result({ approvalId: 7 })).map(({ requirement, code, pointer }) => ({ requirement, code, pointer })),
    [{ requirement: "ASR-079", code: "schema.type", pointer: "/approvalId" }]);
});

test("validation never supplies approvals from outcomes or policy settings", () => {
  for (const status of ["completed", "denied", "cancelled"]) {
    const checked = validate(lines(header(), info({ approval: "never", asks: "never" }), call(), result({ status })));
    assert.deepEqual(checked.diagnostics, []);
    assert.equal(checked.records.some(({ value }) => value.type === "approval"), false);
  }
});

test("native policies retain any JSON value without coercion", () => {
  for (const value of ["", "native-policy", {}, { roots: ["/work"], network: false, unknown: null }, null, [], [{ tool: "shell", effect: "ask" }], false, true, 0]) {
    const record = info({ approval: value, sandbox: value });
    const before = structuredClone(record);
    assert.deepEqual(validateRecord(record), []);
    assert.deepEqual(record, before);
  }
  assert.ok(validateRecord(info({ mode: {} })).length > 0);
});

test("asks and outer boundaries have optional facts and open vocabularies", () => {
  for (const value of ["always", "sometimes", "never", "future", "_vendor", ""]) {
    assert.deepEqual(validateRecord(info({ asks: value, externalSandbox: { kind: value, source: value, native: null } })), []);
  }
  for (const asks of [[], false, 0, {}]) assert.ok(validateRecord(info({ asks })).some(({ requirement }) => requirement === "ASR-072"));
  for (const field of ["externalSandbox", "modelSettings"]) {
    assert.deepEqual(validateRecord(info({ [field]: {} })), []);
    for (const value of [[], false, "none"]) assert.ok(validateRecord(info({ [field]: value })).length > 0);
  }
});

test("configured model settings share call-setting types without call-setting requirements", () => {
  for (const modelSettings of [{}, { maxOutputTokens: 0, temperature: 0, reasoningEffort: "high", serviceTier: "_future" }]) {
    assert.deepEqual(validateRecord(info({ modelSettings })), []);
  }
  for (const maxOutputTokens of [-1, 0.5, false, "10"]) {
    assert.ok(validateRecord(info({ modelSettings: { maxOutputTokens } })).some(({ requirement }) => requirement === "ASR-020"));
  }
  const stream = lines(header(), info({ modelSettings: { maxOutputTokens: "literal" } }));
  for (const literal of ["9007199254740992.5", "1e-999", "-1e-999"]) {
    assert.equal(validate(stream.replace('"literal"', literal)).valid, false);
  }
});

test("scheduled and external arrivals preserve a separate recorded human author and person", () => {
  for (const origin of ["scheduled", "external", "future"]) {
    assert.deepEqual(validateRecord(message({ origin, author: "human", person: { id: "sender" } })), []);
    assert.deepEqual(validateRecord(message({ content: [{ type: "text", text: "", origin }] })), []);
  }
});

test("derivedFrom accepts only a digest of the defined shape", () => {
  assert.deepEqual(validateRecord(header({ derivedFrom: { sha256: "a".repeat(64) } })), []);
  for (const derivedFrom of [null, [], {}, { sha256: "a".repeat(63) }, { sha256: "A".repeat(64) }, { sha256: "a".repeat(64) + "\n" }, { sha256: 1 }]) {
    assert.ok(validateRecord(header({ derivedFrom })).some(({ requirement }) => requirement === "ASR-060"));
  }
});

test("redaction and manifest examples refer to the exact original file bytes", () => {
  const bytes = read("approvals-and-policy.jsonl");
  const redacted = validate(read("approvals-redacted.jsonl"));
  assert.deepEqual(redacted.diagnostics, []);
  assert.equal(redacted.records[0].value.derivedFrom.sha256, sha256(bytes));
  assert.ok(redacted.records[0].value.missing.includes("prompt_text"));
  assert.deepEqual(redacted.records[0].value.producer, { name: "example-redactor", version: "1.0", method: "converter", source: "agent-session-record-0.1" });
  assert.equal(redacted.records.find(({ value }) => value.id === "prompt").value.truncated, true);
  const entry = manifest().entries[0];
  assert.equal(entry.sha256, sha256(bytes));
  assert.equal(entry.byteLength, bytes.length);
  assert.notEqual(entry.sha256, sha256(bytes.toString().replaceAll("\n", "\r\n")));
});

test("manifest accepts empty windows, linked windows, failed receipts and unreadable files", () => {
  const doc = manifest();
  assert.deepEqual(validateManifest(JSON.stringify(doc)).diagnostics, []);
  doc.previousManifest = { sha256: "b".repeat(64) };
  doc.entries = [];
  assert.deepEqual(validateRecord(doc, "manifest"), []);
  for (const status of ["failed", "unreadable", "future"]) {
    doc.entries = [{ status, receivedAt: "2026-10-30T18:30:00Z", uploader: "account-7", reason: "Source unavailable", ...(status === "unreadable" ? { sha256: "c".repeat(64), byteLength: 0 } : {}) }];
    assert.deepEqual(validateRecord(doc, "manifest"), []);
  }
  doc.entries = [manifest().entries[0], { ...manifest().entries[0], replaces: { sha256: "a".repeat(64) }, producer: { method: "future" } }];
  assert.deepEqual(validateRecord(doc, "manifest"), []);
});

test("manifest checks received evidence, failure reasons, hashes, timestamps and session references", () => {
  for (const field of ["session", "sha256", "byteLength", "producer", "status", "receivedAt", "uploader"]) {
    const doc = manifest();
    delete doc.entries[0][field];
    assert.ok(validateRecord(doc, "manifest").length > 0, field);
  }
  for (const fields of [{ byteLength: -1 }, { byteLength: 1.5 }, { sha256: "ABC" }, { session: "codex:s#record" }, { receivedAt: "2026-02-30T00:00:00Z" }, { uploader: "" }, { producer: {} }, { replaces: {} }]) {
    const doc = manifest();
    Object.assign(doc.entries[0], fields);
    assert.ok(validateRecord(doc, "manifest").length > 0, JSON.stringify(fields));
  }
  for (const status of ["failed", "unreadable", "future", "recieved"]) {
    const doc = manifest();
    doc.entries[0].status = status;
    assert.ok(validateRecord(doc, "manifest").length > 0);
  }
});

test("manifest requires its v0 schema URL", () => {
  for (const schema of [undefined, null, "https://example.com/manifest.json", "https://agentsessionrecord.org/schema/v1/manifest.schema.json"]) {
    const doc = manifest();
    doc.$schema = schema;
    assert.equal(validateManifest(JSON.stringify(doc)).valid, false);
  }
});

test("manifest warns on unknown statuses without closing the vocabulary", () => {
  const doc = manifest();
  doc.entries[0].status = "recieved";
  doc.entries[0].reason = "Unrecognized collector status";
  const checked = validateManifest(JSON.stringify(doc));
  assert.equal(checked.valid, true);
  assert.deepEqual(checked.diagnostics, [{ severity: "warning", code: "manifest-unknown-status", line: 1, pointer: "/entries/0/status", message: "Unknown receipt status." }]);
});

test("manifest windows include the start and exclude the end in absolute time", () => {
  const doc = manifest();
  for (const [time, outside] of [
    ["2026-10-30T18:00:00Z", false], ["2026-10-30T14:00:00-04:00", false],
    ["2026-10-30T18:59:59.999999Z", false], ["2026-10-30T19:00:00Z", true],
    ["2026-10-30T17:59:59.999999Z", true], ["2026-10-31T18:30:00Z", true],
  ]) {
    doc.entries[0].receivedAt = time;
    const checked = validateManifest(JSON.stringify(doc));
    assert.equal(checked.valid, true);
    assert.equal(checked.diagnostics.some(({ code }) => code === "manifest-receipt-outside-window"), outside, time);
  }
  doc.window = { start: "2026-10-30T18:00:00.0001Z", end: "2026-10-30T18:00:00.0003Z" };
  doc.entries[0].receivedAt = "2026-10-30T18:00:00.0002Z";
  assert.deepEqual(validateManifest(JSON.stringify(doc)).diagnostics, []);
  doc.window.end = doc.window.start;
  assert.ok(validateManifest(JSON.stringify(doc)).diagnostics.some(({ code }) => code === "manifest-window-order"));
  doc.window.end = "2026-10-30T17:00:00Z";
  assert.ok(validateManifest(JSON.stringify(doc)).diagnostics.some(({ code }) => code === "manifest-window-order"));
  doc.window = { start: "2016-12-31T23:59:60Z", end: "2017-01-01T00:00:00Z" };
  doc.entries[0].receivedAt = "2016-12-31T23:59:60.5Z";
  assert.deepEqual(validateManifest(JSON.stringify(doc)).diagnostics, []);
  doc.entries[0].receivedAt = doc.window.end;
  assert.ok(validateManifest(JSON.stringify(doc)).diagnostics.some(({ code }) => code === "manifest-receipt-outside-window"));
});

test("manifest parsing rejects corrupt bytes, syntax, duplicate keys and rounded byte counts without requirement IDs", () => {
  const doc = JSON.stringify(manifest());
  for (const bytes of [Buffer.from([0xff]), "{bad}", doc.replace('"machine":', '"machine":"duplicate","machine":'), doc.replace(/"byteLength":\d+/, '"byteLength":9007199254740992.5')]) {
    const checked = validateManifest(bytes);
    assert.equal(checked.valid, false);
    assert.ok(checked.diagnostics.length > 0);
    assert.ok(checked.diagnostics.every((problem) => !Object.hasOwn(problem, "requirement")));
  }
  assert.deepEqual(checkBlock(doc, "json"), []);
  assert.ok(checkBlock(doc.replace('"collector":', '"collector":null,"duplicateCollector":'), "json").length > 0);
});

test("CLI detects manifests by filename and by schema on stdin", (t) => {
  const bin = new URL("../bin/asr-validate.js", import.meta.url);
  const doc = manifest();
  const filename = path.join(temporaryDirectory(t), "receipt.manifest.json");
  writeFileSync(filename, JSON.stringify(doc, null, 2));
  for (const [arg, input] of [[filename, undefined], ["-", read("collection.manifest.json")]]) {
    const proc = spawnSync(process.execPath, [bin.pathname, "--json", arg], { input, encoding: "utf8" });
    assert.equal(proc.status, 0, proc.stderr);
    assert.equal(JSON.parse(proc.stdout).kind, "manifest");
  }
  delete doc.$schema;
  writeFileSync(filename, JSON.stringify(doc));
  const missingSchema = spawnSync(process.execPath, [bin.pathname, "--json", filename], { encoding: "utf8" });
  assert.equal(missingSchema.status, 1);
  assert.equal(JSON.parse(missingSchema.stdout).kind, "manifest");
  writeFileSync(filename, "{}");
  const proc = spawnSync(process.execPath, [bin.pathname, filename], { encoding: "utf8" });
  assert.equal(proc.status, 1);
  assert.doesNotMatch(proc.stdout, /ASR-|undefined/);
});
