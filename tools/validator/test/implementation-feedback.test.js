import { test } from "node:test";
import assert from "node:assert/strict";
import { validate, validateRecord, validateFile } from "../src/index.js";
import { isBase64 } from "../src/schema/base64.js";
import { header, inference, call, result, message, lines } from "./helpers.js";

const info = (agentSettings) => ({ type: "session_info", id: "settings", agentSettings });

test("an identified inference can omit its model with a header or later loss declaration", () => {
  const record = { type: "inference", id: "response-1", usage: { inputTokens: 0 } };
  assert.deepEqual(validateRecord(record), []);
  assert.deepEqual(validate(lines(header({ missing: ["model"] }), record)).diagnostics, []);
  assert.deepEqual(validate(lines(header(), record, { type: "session_info", id: "loss", missing: ["model"] })).diagnostics, []);
  assert.deepEqual(validate(lines(header(), record)).diagnostics.map(({ code }) => code), ["missing-model-loss"]);
  for (const model of [null, {}, { provider: "example" }]) assert.ok(validateRecord({ ...record, model }).length > 0);
  assert.deepEqual(validate(lines(header(), record, { type: "session_info", id: "loss", missing: [] })).diagnostics.map(({ code }) => code), ["missing-model-loss"]);
});

test("result arguments preserve null, empty text and structured rewrites without changing calls", () => {
  for (const fields of [{ input: null }, { inputText: "" }, { input: { command: "echo executed" } }]) {
    const original = call({ input: { command: "echo requested" } });
    const output = validate(lines(header(), original, result(fields)));
    assert.deepEqual(output.diagnostics, []);
    assert.deepEqual(output.records[1].value, original);
    for (const [key, value] of Object.entries(fields)) assert.deepEqual(output.records[2].value[key], value);
  }
  assert.ok(validateRecord(result({ input: null, inputText: "null" })).some(({ requirement }) => requirement === "ASR-076"));
  assert.ok(validateRecord(result({ inputText: 1 })).some(({ requirement }) => requirement === "ASR-076"));
});

test("null clears apply only to configured settings and keep valid falsy values", () => {
  for (const field of ["mode", "approval", "sandbox", "asks", "externalSandbox", "modelSettings"]) assert.deepEqual(validateRecord(info({ [field]: null })), []);
  for (const field of ["reasoningEffort", "serviceTier", "temperature", "maxOutputTokens"]) {
    assert.deepEqual(validateRecord(info({ modelSettings: { [field]: null } })), []);
    assert.ok(validateRecord(inference({ settings: { [field]: null } })).length > 0);
  }
  for (const literal of ["9007199254740992.5", "-1e-999", "1e-999"]) {
    assert.equal(validate(lines(header(), info({ modelSettings: { maxOutputTokens: "value" } })).replace('"value"', literal)).valid, false);
  }
  assert.deepEqual(validateRecord(info({ mode: "", asks: "", modelSettings: { maxOutputTokens: 0, temperature: 0 } })), []);
});

test("completion example retains intervening events, result time, effective input and explicit lifecycle times", () => {
  const output = validateFile(new URL("../../../examples/live-recording.jsonl", import.meta.url).pathname);
  assert.deepEqual(output.diagnostics, []);
  const records = output.records.map(({ value }) => value);
  assert.deepEqual(records.map(({ id }) => id), ["header", "call", "notice", "decision", "result", "end"]);
  assert.equal(records[4].ts, "2026-10-31T12:00:04Z");
  assert.deepEqual(records[4].input, { command: "echo executed" });
  assert.equal(records[0].startedAt, "2026-10-31T12:00:00Z");
  assert.equal(records[5].endedAt, "2026-10-31T12:00:05Z");
});

test("revision example links repeated output to one copied inference and keeps unknown new model identity", () => {
  const output = validateFile(new URL("../../../examples/partial-evidence.jsonl", import.meta.url).pathname);
  assert.deepEqual(output.diagnostics, []);
  const records = output.records.map(({ value }) => value);
  const calls = records.filter(({ type }) => type === "inference");
  assert.equal(calls.length, 2);
  assert.equal(records.filter(({ inferenceId }) => inferenceId === "copied-call").length, 2);
  assert.equal(calls.filter(({ copiedFrom }) => !copiedFrom).reduce((sum, record) => sum + record.usage.inputTokens, 0), 12);
  assert.equal(calls[1].id, "9007199254740993");
  assert.equal(Object.hasOwn(calls[1], "model"), false);
});

test("base64 check agrees with the alphabet and padding grammar", () => {
  const reference = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$(?![\s\S])/;
  const alphabet = ["A", "/", "=", "?", "\n"];
  function check(prefix, depth) {
    assert.equal(isBase64(prefix), reference.test(prefix), JSON.stringify(prefix));
    if (depth) for (const char of alphabet) check(prefix + char, depth - 1);
  }
  check("", 7);
  for (const value of ["YQ==", "YR==", "YWJ=", "az09", "+/AA", "AAAA\r", "AAAA\u2028"]) assert.equal(isBase64(value), reference.test(value));
});

test("multi-megabyte image, audio and resource data validate without a regexp stack", () => {
  const large = "A".repeat(8 * 1024 * 1024);
  for (const part of [
    { type: "image", mimeType: "image/png", data: large },
    { type: "audio", mimeType: "audio/wav", data: large + "AA==" },
    { type: "resource", resource: { uri: "file:///media", blob: large + "AAA=" } },
  ]) assert.deepEqual(validateRecord(message({ content: [part] })), []);
  for (const data of [large + "A", large.slice(0, -1) + "?", large + "====", "=" + large.slice(1)]) {
    assert.ok(validateRecord(message({ content: [{ type: "image", mimeType: "image/png", data }] })).some(({ code, requirement }) => code === "schema.format" && requirement === "ASR-013"));
  }
});
