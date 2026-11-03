import { test } from "node:test";
import assert from "node:assert/strict";
import { validate, validateRecord } from "../src/index.js";
import { header, inference, lines } from "./helpers.js";

const info = (agentSettings) => ({ type: "session_info", id: "settings", agentSettings });
const hasError = (record, requirement, pointer) => assert.ok(
  validateRecord(record).some((problem) => problem.requirement === requirement && problem.pointer === pointer),
  JSON.stringify(validateRecord(record)),
);

test("user accepts any recorded identity field and keeps the source vocabulary open", () => {
  for (const field of ["id", "email", "name"]) {
    for (const value of ["recorded identity"]) {
      assert.deepEqual(validateRecord(header({ user: { [field]: value } })), []);
      for (const source of ["agent_account", "git", "os", "configured", "future_source", "_example", ""]) {
        assert.deepEqual(validateRecord(header({ user: { [field]: value, source } })), []);
      }
    }
  }
});

test("user needs an identity even when source or future fields exist", () => {
  for (const user of [{}, { source: "configured" }, { futureIdentity: "account-7" }]) {
    hasError(header({ user }), "ASR-019", "/user");
  }
});

test("identity and settings objects reject nonobjects", () => {
  for (const value of [null, false, [], "plan", 1]) {
    hasError(header({ user: value }), "ASR-019", "/user");
    hasError(info(value), "ASR-020", "/agentSettings");
    hasError(inference({ settings: value }), "ASR-035", "/settings");
  }
});

test("identity and agent-setting fields retain strings without coercion", () => {
  for (const value of [null, false, 0, [], {}]) {
    for (const field of ["id", "email", "name", "source"]) {
      hasError(header({ user: { id: "account-7", [field]: value } }), "ASR-019", `/user/${field}`);
    }
    if (value !== null) hasError(info({ mode: value }), "ASR-020", "/agentSettings/mode");
    for (const field of ["reasoningEffort", "serviceTier"]) {
      hasError(inference({ settings: { [field]: value } }), "ASR-035", `/settings/${field}`);
    }
  }
});

test("partial and empty agent settings are valid session updates", () => {
  for (const agentSettings of [{}, { mode: "plan" }, { approval: "" }, { sandbox: "future-policy" },
    { mode: "execute", approval: "on-request", sandbox: "workspace-write" }]) {
    assert.deepEqual(validate(lines(header(), info(agentSettings))).diagnostics, []);
  }
});

test("model settings allow recorded numeric values and keep optional fields optional", () => {
  for (const settings of [{}, { reasoningEffort: "" }, { serviceTier: "future-tier" },
    { maxOutputTokens: 0 }, { maxOutputTokens: 2048 }, { temperature: 0 }, { temperature: -0.5 }, { temperature: 3.5 }]) {
    assert.deepEqual(validateRecord(inference({ settings })), []);
  }
  for (const maxOutputTokens of [-1, 0.5, "2048", null, false]) {
    hasError(inference({ settings: { maxOutputTokens } }), "ASR-035", "/settings/maxOutputTokens");
  }
  for (const temperature of ["0", null, false, [], {}]) {
    hasError(inference({ settings: { temperature } }), "ASR-035", "/settings/temperature");
  }
});

test("token limits are checked from JSON literals without rounding away invalid values", () => {
  for (const literal of ["9007199254740992.5", "1e-999", "-1e-999"]) {
    const body = lines(header(), inference({ settings: { maxOutputTokens: "limit" } })).replace('"limit"', literal);
    assert.ok(validate(body).diagnostics.some(({ requirement, pointer }) => requirement === "ASR-035" && pointer === "/settings/maxOutputTokens"));
  }
  const body = lines(header(), inference({ settings: { maxOutputTokens: "limit" } })).replace('"limit"', "9007199254740993");
  assert.deepEqual(validate(body).diagnostics, []);
});

test("validation preserves unknown fields, verbatim strings and absent settings without adding defaults", () => {
  for (const record of [header(), inference(), header({ user: { id: "account-7", future: { value: 1 } } }),
    info({ mode: "Plan Mode", future: { value: false } }),
    inference({ settings: { reasoningEffort: "Extra High", serviceTier: "Priority", temperature: 0, future: { value: null } },
      _meta: { "com.example.coder": { topP: 0.8 } } })]) {
    const before = structuredClone(record);
    assert.deepEqual(validateRecord(record), []);
    assert.deepEqual(record, before);
  }
});
