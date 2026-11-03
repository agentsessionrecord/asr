import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, mkdirSync, writeFileSync, symlinkSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { validate, validateStream, validateFileStream, validateDirectory } from "../src/index.js";
import { header, message, lines, temporaryDirectory } from "./helpers.js";

async function* chunks(bytes, size) {
  for (let start = 0; start < bytes.length; start += size) yield bytes.subarray(start, start + size);
}

async function equivalent(bytes, filename, size) {
  const expected = validate(bytes, { filename });
  const output = await validateStream(chunks(bytes, size), { filename });
  assert.equal(output.valid, expected.valid, filename);
  assert.equal(output.kind, expected.kind, filename);
  assert.equal(output.recordCount, expected.records.length, filename);
  assert.deepEqual(output.diagnostics, expected.diagnostics, filename);
  const summary = await validateStream(chunks(bytes, size), { filename, summary: true });
  const { diagnostics, ...rest } = output;
  assert.deepEqual(summary, rest, filename);
  assert.equal(summary.errors + summary.warnings, diagnostics.length);
}

test("streamed framing, schemas and relationships match every fixture and example", async () => {
  for (const folder of ["conformance/fixtures", "examples"]) {
    const base = new URL(`../../../${folder}/`, import.meta.url);
    for (const name of readdirSync(base, { recursive: true }).filter((file) => file.endsWith(".jsonl") || file.endsWith(".manifest.json"))) {
      const filename = new URL(name, base).pathname;
      const bytes = readFileSync(filename);
      await equivalent(bytes, filename, 1);
      await equivalent(bytes, filename, 65536);
    }
  }
});

test("streaming handles empty input, invalid UTF-8, split Unicode and CRLF, duplicate keys and numeric spelling", async () => {
  for (const bytes of [Buffer.alloc(0), Buffer.from('{"type":'),
    Buffer.from(lines(header(), message({ content: [{ type: "text", text: "雪😀\r\n" }] })).replaceAll("\n", "\r\n")),
    Buffer.concat([Buffer.from(lines(header())), Buffer.from([0xff, 10]), Buffer.from(lines(message()))]),
    Buffer.from(lines(header()) + '{"type":"gap","id":"g","reason":"unknown","count":9007199254740992.5}\n'),
    Buffer.from(lines(header()) + '{"type":"message","id":"x","\\u0069d":"y"}\n')]) {
    await equivalent(bytes, "", 1);
  }
  await assert.rejects(validateStream(chunks(Buffer.alloc(0), 1), { mode: "wrong" }), /mode/);
});

test("explicit annotations and manifests work and leading schema detection handles chunk boundaries", async () => {
  const bytes = readFileSync(new URL("../../../examples/collection.manifest.json", import.meta.url));
  await equivalent(bytes, "", 1);
  const doc = JSON.parse(bytes);
  const reordered = Buffer.from(JSON.stringify({ entries: doc.entries, ...doc }));
  assert.deepEqual((await validateStream(chunks(reordered, 1), { mode: "manifest" })).diagnostics, []);
  assert.equal((await validateStream([], { mode: "annotations" })).valid, true);
  await assert.rejects(validateStream((async function* () { yield Buffer.from("{"); throw new Error("source failed"); })()), /source failed/);
});

test("directories yield each file once, skip unrelated files and symlinks, and isolate relationships", async (t) => {
  const directory = temporaryDirectory(t);
  mkdirSync(path.join(directory, "nested"));
  writeFileSync(path.join(directory, "one.jsonl"), lines(header(), message()));
  writeFileSync(path.join(directory, "nested", "two.jsonl"), lines(header(), message()));
  writeFileSync(path.join(directory, "ignored.json"), "not an ASR file");
  symlinkSync(directory, path.join(directory, "loop"));
  const files = [];
  for await (const output of validateDirectory(directory, { summary: true })) {
    assert.equal(output.valid, true);
    assert.equal(output.recordCount, 2);
    assert.equal(Object.hasOwn(output, "diagnostics"), false);
    files.push(output.file);
  }
  assert.equal(files.length, 2);
  assert.deepEqual((await validateFileStream(files[0])).diagnostics, []);
  await assert.rejects(validateFileStream(path.join(directory, "absent.jsonl")), /ENOENT/);
  const bin = new URL("../bin/asr-validate.js", import.meta.url).pathname;
  for (const args of [["--json", directory], ["--json", "--summary", directory]]) {
    const proc = spawnSync(process.execPath, [bin, ...args], { encoding: "utf8" });
    assert.equal(proc.status, 0, proc.stderr);
    const report = JSON.parse(proc.stdout);
    const summary = report.summary ?? report;
    assert.equal(summary.files, 2);
    assert.equal(summary.records, 4);
    assert.equal(summary.errors, 0);
    if (!args.includes("--summary")) assert.equal(report.files.length, 2);
  }
});

test("summary validation exceeds heap size in content without retaining records or diagnostics", () => {
  const module = new URL("../src/index.js", import.meta.url).href;
  const script = `
    import { validateStream } from ${JSON.stringify(module)};
    async function* source() {
      yield ${JSON.stringify(lines(header()))};
      const content = "x".repeat(65536);
      for (let n = 0; n < 2048; n++) yield JSON.stringify({type: "com.example/event", id: String(n), content}) + "\\n";
    }
    console.log(JSON.stringify(await validateStream(source(), {summary: true})));
  `;
  const proc = spawnSync(process.execPath, ["--max-old-space-size=64", "--input-type=module", "-e", script], { encoding: "utf8" });
  assert.equal(proc.status, 0, proc.stderr);
  const output = JSON.parse(proc.stdout);
  assert.equal(output.recordCount, 2049);
  assert.equal(output.warnings, 2048);
  assert.equal(output.counts["warning:unknown-type"], 2048);
  assert.equal(Object.hasOwn(output, "records"), false);
  assert.equal(Object.hasOwn(output, "diagnostics"), false);
});
