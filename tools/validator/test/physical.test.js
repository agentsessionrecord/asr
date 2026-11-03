import { test } from "node:test";
import assert from "node:assert/strict";
import { validate } from "../src/index.js";
import { readJsonl, duplicateKeys } from "../src/jsonl.js";
import { header, message, lines } from "./helpers.js";

test("file order survives backwards timestamps and unknown data survives parsing", () => {
  const first = message({ id: "late", ts: "2026-10-27T09:00:00Z", future: { n: 0, b: false, s: "" } });
  const second = message({ id: "early", ts: "2026-10-26T09:00:00Z" });
  const output = validate(lines(header(), first, second));
  assert.equal(output.valid, true);
  assert.deepEqual(output.records.map(({ value }) => value), [header(), first, second]);
});

for (const [name, malformed, code] of [
  ["malformed JSON", Buffer.from('{"type":}\n'), "invalid-json"],
  ["blank line", Buffer.from("\n"), "blank-line"],
  ["whitespace line", Buffer.from(" \t\r\n"), "blank-line"],
  ["non-object", Buffer.from("[]\n"), "non-object"],
  ["null", Buffer.from("null\n"), "non-object"],
  ["invalid UTF-8", Buffer.from([0xff, 0x0a]), "invalid-utf8"],
  ["escaped duplicate key", Buffer.from('{"id":"a","\\u0069d":"b"}\n'), "duplicate-key"],
  ["byte order mark", Buffer.from('\ufeff{"type":"message","id":"bad"}\n'), "invalid-json"],
]) test(`${name} is an error and recovery retains the next record`, () => {
  const output = validate(Buffer.concat([Buffer.from(lines(header())), malformed, Buffer.from(lines(message()))]));
  assert.equal(output.valid, false);
  assert.deepEqual(output.records.map(({ line }) => line), [1, 3]);
  assert.ok(output.diagnostics.some((problem) => problem.code === code && problem.line === 2 && problem.requirement === "ASR-001"));
});

for (const tail of [Buffer.from('{"type":'), Buffer.from(JSON.stringify(message())), Buffer.from([0xf0, 0x9f]), Buffer.from(" ")]) {
  test(`incomplete tail is deferred (${tail.toString("hex")})`, () => {
    const output = validate(Buffer.concat([Buffer.from(lines(header())), tail]));
    assert.equal(output.valid, true);
    assert.equal(output.records.length, 1);
    assert.deepEqual(output.diagnostics.map(({ code, severity }) => [code, severity]), [["incomplete-line", "warning"]]);
  });
}

test("an incomplete first line waits without a missing-header error", () => {
  assert.deepEqual(validate('{"type":"session"').diagnostics.map(({ code }) => code), ["incomplete-line"]);
  assert.equal(validate("").valid, false);
  assert.equal(validate("", { filename: "empty.annotations.jsonl" }).valid, true);
});

test("CRLF and ordinary JSON numeric spelling are accepted", () => {
  const source = lines(header(), { type: "gap", id: "gap", reason: "unknown", count: 1 }).replace('"count":1', '"count":1.0').replaceAll("\n", "\r\n");
  assert.deepEqual(validate(source).diagnostics, []);
});

test("large JSON integers and unknown numbers have no binary64 validation limit", () => {
  for (const count of ["9007199254740993", "1e400", "100e-2", "0e-9999"]) {
    const source = lines(header()) + `{"type":"gap","id":"g","reason":"unknown","count":${count}}\n`;
    const output = validate(source);
    assert.deepEqual(output.diagnostics, []);
    assert.ok(output.records[1].raw.includes(count));
  }
  const source = lines(header()) + '{"type":"message","id":"m","role":"user","content":[],"future":9007199254740993}\n';
  assert.ok(validate(source).records[1].raw.includes("9007199254740993"));
});

test("rounding and underflow cannot hide fractional counts or negative durations", () => {
  for (const count of ["9007199254740992.5", "1.00000000000000001", "1e-400", "-1e-400"]) {
    const output = validate(lines(header()) + `{"type":"gap","id":"g","reason":"unknown","count":${count}}\n`);
    assert.equal(output.valid, false, count);
    assert.ok(output.diagnostics.some(({ requirement }) => requirement === "ASR-039"));
  }
  const output = validate(lines(header()) + '{"type":"inference","id":"i","model":{"id":"model"},"durationMs":-1e-400}\n');
  assert.equal(output.valid, false);
});

test("duplicate keys are local to each object and escaped pointers are precise", () => {
  const text = '{"nested":[{"a/b~c":0,"a\\u002fb~c":1},{"ok":0}],"ok":1}';
  JSON.parse(text);
  assert.deepEqual(duplicateKeys(text), ["/nested/0/a~1b~0c"]);
  const noDuplicates = '{"empty":"","nested":[{"a":"quotes \\\" and slash \\\\"},{"a":"other"}],"__proto__":{"x":1}}';
  JSON.parse(noDuplicates);
  assert.deepEqual(duplicateKeys(noDuplicates), []);
});

test("duplicate-key scan handles deeply nested JSON without recursive traversal", () => {
  const text = '{"type":"com.example/deep","id":"deep","data":' + '['.repeat(2000) + '0' + ']'.repeat(2000) + '}\n';
  assert.equal(readJsonl(text).records.length, 1);
});
