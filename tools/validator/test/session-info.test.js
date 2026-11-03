import { test } from "node:test";
import assert from "node:assert/strict";
import { validate, validateRecord } from "../src/index.js";
import { buildSchemas } from "../src/schema/build.js";
import { header, inference, lines } from "./helpers.js";

test("tool lists retain captured definitions and can be the only session update", () => {
  const tools = [{ name: "lookup", description: "Recorded instructions\n", inputSchema: { type: "object", properties: { query: { type: "string" } } }, source: "docs" }];
  const records = [header(), { type: "session_info", id: "tools", tools }, inference(), { type: "session_info", id: "empty", tools: [] }];
  const checked = validate(lines(...records));
  assert.deepEqual(checked.diagnostics, []);
  assert.deepEqual(checked.records.map(({ value }) => value), records);
  assert.deepEqual(validateRecord({ type: "session_info", id: "minimal", tools: [{ name: "read" }] }), []);
});

test("tool definitions require a name and typed optional text", () => {
  for (const tools of [null, {}, "read", [null], [{}], [{ name: false }], [{ name: "read", description: [] }], [{ name: "read", source: 1 }]]) {
    assert.ok(validateRecord({ type: "session_info", id: "tools", tools }).some(({ requirement }) => requirement === "ASR-074"));
  }
  assert.deepEqual(validateRecord({ type: "session_info", id: "tools", tools: [{ name: "read", inputSchema: false, future: {} }] }), []);
});

test("loss updates retain additions and empty arrays without altering the header", () => {
  const records = [header({ missing: ["usage"] }), { type: "session_info", id: "loss", missing: ["approvals", "future_loss"] }, { type: "session_info", id: "empty", missing: [] }];
  const checked = validate(lines(...records));
  assert.deepEqual(checked.diagnostics, []);
  assert.deepEqual(checked.records.map(({ value }) => value), records);
  for (const missing of [null, {}, "approvals", [false], [1]]) {
    assert.ok(validateRecord({ type: "session_info", id: "loss", missing }).some(({ requirement }) => requirement === "ASR-057"));
  }
});

test("the core schema defines standalone approvals and asks", () => {
  const defs = buildSchemas().record.$defs;
  assert.equal(defs["record.approval"]["x-asr"], "ASR-073");
  assert.deepEqual(defs.AgentSettings.properties.asks.type, ["string", "null"]);
  assert.equal(Object.hasOwn(defs["record.tool_result"].properties, "approvals"), false);
  assert.equal(Object.hasOwn(defs.AgentSettings.properties, "access"), false);
});
