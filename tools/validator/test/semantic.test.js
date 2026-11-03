import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import path from "node:path";
import { validate, validateRecord } from "../src/index.js";
import { header, message, call, result, vcs, inference, annotation, lines, session, commit, otherCommit, temporaryDirectory } from "./helpers.js";

const codes = (output) => output.diagnostics.map(({ code }) => code);
test("session must be first and cannot recur", () => {
  assert.ok(codes(validate(lines(message(), header()))).includes("missing-header"));
  assert.ok(codes(validate(lines(header(), header({ id: "second" })))).includes("extra-header"));
  assert.ok(codes(validate("\n" + lines(header()))).includes("missing-header"));
});

test("record IDs are unique across known and unknown types", () => {
  assert.ok(codes(session(message(), { type: "com.example/event", id: "message" })).includes("duplicate-id"));
  assert.ok(codes(session(message({ id: "header" }))).includes("duplicate-id"));
});

test("forward call and inference references resolve", () => {
  assert.deepEqual(session(result(), call({ inferenceId: "model" }), inference()).diagnostics, []);
});

test("a callId has at most one result even with distinct record IDs or no call", () => {
  for (const calls of [[call()], []]) {
    const output = session(...calls, result({ status: "failed" }), result({ id: "second-result", status: "completed" }));
    assert.equal(output.valid, false);
    assert.deepEqual(output.diagnostics.filter(({ severity }) => severity === "error").map(({ code, requirement }) => [code, requirement]), [["duplicate-result", "ASR-026"]]);
  }
  const a = result(), b = result({ id: "other" });
  delete a.callId;
  delete b.callId;
  assert.equal(session(a, b).valid, true);
  assert.deepEqual(session(call(), result(), call({ id: "c2", callId: "c2" }), result({ id: "r2", callId: "c2" })).diagnostics, []);
});

test("duplicate call IDs leave every call and its result unpaired", () => {
  const output = session(call(), call({ id: "second-call" }), result());
  assert.equal(output.valid, true);
  assert.deepEqual(codes(output), ["call-without-result", "call-without-result", "unpaired-result"]);
  assert.ok(output.diagnostics.every(({ severity, requirement }) => severity === "warning" && requirement === "ASR-070"));
});

test("tool warnings distinguish absence, missing result and unknown inference", () => {
  const nameless = call();
  delete nameless.name;
  assert.deepEqual(codes(session({ ...nameless, inferenceId: "missing" })), ["call-without-result", "missing-tool-name", "unresolved-inference"]);
  assert.deepEqual(codes(session(call({ name: "" }), result({ status: "_future" }))), []);
});

test("unpaired results warn even without a callId and do not imply failure", () => {
  const record = result();
  delete record.callId;
  assert.deepEqual(codes(session(record, result({ id: "r2", callId: "unknown" }))), ["unpaired-result", "unpaired-result"]);
});

test("inferenceId must match an inference, not any record", () => {
  assert.deepEqual(codes(session(message({ inferenceId: "other" }), message({ id: "other" }))), ["unresolved-inference"]);
});

test("parent count is checked without inspecting Git", () => {
  assert.deepEqual(session(vcs({ parents: [commit], parentCount: 1 })).diagnostics, []);
  assert.deepEqual(codes(session(vcs({ parents: [], parentCount: 1 }))), ["parent-count"]);
  assert.deepEqual(session(vcs({ parentCount: 0 })).diagnostics, []);
  assert.deepEqual(session(vcs({ parents: [] })).diagnostics, []);
});

test("rewrite endpoints must differ in streams and annotation payloads", () => {
  assert.deepEqual(codes(session(vcs({ rewrites: [{ from: commit, to: commit }] }))), ["identical-rewrite"]);
  assert.deepEqual(session(vcs({ rewrites: [{ from: commit, to: otherCommit }] })).diagnostics, []);
  const data = { action: "rebase", status: "completed", evidence: "observed", parents: [], parentCount: 1, rewrites: [{ from: commit, to: commit }] };
  assert.deepEqual(codes(validate(lines(annotation({ kind: "vcs", data })))), ["identical-rewrite", "parent-count"]);
});

test("full commit lengths agree across VCS fields and annotation payloads", () => {
  const sha256 = "c".repeat(64);
  for (const fields of [{ parents: [sha256] }, { headBefore: sha256 }, { headAfter: sha256 },
    { rewrites: [{ from: sha256, to: commit }] }, { pr: { url: "https://example.com/pr/1", mergeCommit: sha256 } },
    { pr: { url: "https://example.com/pr/1", headCommit: sha256 } }, { pr: { url: "https://example.com/pr/1", commits: [sha256] } }]) {
    const data = vcs({ commit, ...fields });
    assert.ok(codes(session(data)).includes("mixed-commit-lengths"));
    assert.ok(codes(validate(lines(annotation({ kind: "vcs", data })))).includes("mixed-commit-lengths"));
  }
  assert.deepEqual(session(vcs({ commit: sha256, parents: ["d".repeat(64)] })).diagnostics, []);
  // Independent repositories can use different object formats in one stream.
  assert.deepEqual(session(vcs({ commit }), vcs({ id: "other-vcs", commit: sha256 })).diagnostics, []);
});

test("copiedThrough resolves forward after the header without loading the parent", () => {
  const parent = { session: "codex:unavailable", kind: "fork", copiedThrough: "message" };
  assert.deepEqual(validate(lines(header({ parent }), message())).diagnostics, []);
  for (const copiedThrough of ["missing", "header"]) assert.deepEqual(codes(validate(lines(header({ parent: { ...parent, copiedThrough } }), message()))), ["copied-through"]);
});

test("external lineage links can remain unavailable", () => {
  const parent = { session: "codex:unavailable", kind: "subagent", callId: "unavailable" };
  const copiedFrom = { session: "codex:unavailable", record: "unavailable" };
  assert.deepEqual(validate(lines(header({ parent }), message({ copiedFrom, from: "codex:another" }), call({ subagent: { session: "codex:child" } }), result({ subagent: { session: "codex:child" } }))).diagnostics, []);
});

test("unknown records and extensions warn without interpreting their payload", () => {
  const future = { type: "com.example/task", id: "future", callId: 123, rewrites: [{ from: "same", to: "same" }] };
  const output = validate(lines(header({ extensions: ["example@1"] }), future));
  assert.equal(output.valid, true);
  assert.deepEqual(codes(output), ["unknown-extension", "unknown-type"]);
  assert.deepEqual(output.records[1].value, future);
});

test("annotation detection uses filename or first record type", () => {
  assert.equal(validate(lines(annotation())).kind, "annotations");
  assert.equal(validate(lines(message()), { filename: "facts.annotations.jsonl" }).kind, "annotations");
  assert.equal(validate(lines(header(), annotation())).valid, false);
  assert.ok(codes(validate(lines(header(), annotation()))).includes("annotation-in-session"));
  assert.equal(validate(lines(annotation(), header())).valid, false);
  assert.throws(() => validate("", { mode: "wrong" }), /mode/);
});

test("annotation supersedes needs an earlier annotation, even when at is earlier", () => {
  assert.deepEqual(validate(lines(annotation(), annotation({ id: "a2", at: "2026-10-26T09:00:00Z", supersedes: "a1" }))).diagnostics, []);
  for (const supersedes of ["a1", "future", "missing"]) assert.ok(codes(validate(lines(annotation({ supersedes }), annotation({ id: "future" })))).includes("supersedes-not-earlier"));
  assert.ok(codes(validate(lines(annotation(), annotation()))).includes("duplicate-id"));
  assert.ok(codes(validate(lines(message(), annotation({ supersedes: "message" })), { filename: "test.annotations.jsonl" })).includes("supersedes-not-earlier"));
});

test("excerpts omit file-level relationship checks", () => {
  assert.deepEqual(validateRecord(vcs({ parents: [], parentCount: 1 })), []);
  assert.deepEqual(validateRecord(annotation({ supersedes: "missing" })), []);
});

test("recorded commands and URIs remain data and external files are not needed", (t) => {
  const marker = path.join(temporaryDirectory(t), "must-not-exist");
  t.mock.method(globalThis, "fetch", () => { throw new Error("Network must not be queried."); });
  const records = [
    header({ repos: [{ path: "/no-such-repository", head: commit, remote: "https://invalid.example/repo.git" }] }),
    call({ inputText: `touch ${marker}` }), result({ content: [{ type: "resource_link", uri: "https://invalid.example/content", name: "resource" }] }),
    vcs({ commit }),
  ];
  assert.deepEqual(validate(lines(...records)).diagnostics, []);
  assert.equal(existsSync(marker), false);
});
