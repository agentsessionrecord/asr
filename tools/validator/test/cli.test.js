import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { main } from "../src/cli.js";
import { header, call, annotation, lines, temporaryDirectory } from "./helpers.js";

const bin = fileURLToPath(new URL("../bin/asr-validate.js", import.meta.url));
const run = (args, input) => spawnSync(process.execPath, [bin, ...args], { input, encoding: "utf8" });

test("CLI supports JSON on stdin, warning success and annotation detection", () => {
  const output = run(["--json", "-"], lines(header(), call()));
  assert.equal(output.status, 0, output.stderr);
  const report = JSON.parse(output.stdout);
  assert.equal(report.warnings, 1);
  assert.equal(report.errors, 0);
  assert.equal(report.records, 2);
  assert.equal(report.diagnostics[0].requirement, "ASR-070");
  assert.equal(JSON.parse(run(["-", "--json"], lines(annotation())).stdout).kind, "annotations");
});

test("CLI reports errors and continues after malformed lines", () => {
  const output = run(["-", "--json"], lines(header()) + '{broken}\n' + lines(call()));
  assert.equal(output.status, 1);
  const report = JSON.parse(output.stdout);
  assert.equal(report.records, 2);
  assert.equal(report.errors, 1);
  assert.equal(report.warnings, 1);
});

test("CLI text output locates diagnostics and file suffix selects annotations", (t) => {
  const filename = path.join(temporaryDirectory(t), "facts.annotations.jsonl");
  writeFileSync(filename, lines(header()));
  const output = run([filename]);
  assert.equal(output.status, 1);
  assert.match(output.stdout, /:1.*error ASR-062/);
  assert.equal(JSON.parse(run([filename, "--json"]).stdout).kind, "annotations");
});

test("CLI help, invalid arguments and I/O failures have distinct exit status", async () => {
  assert.equal(run(["--help"]).status, 0);
  assert.match(run(["--help"]).stdout, /faithfulness/);
  const out = [];
  const io = { out: (text) => out.push(text), err: (text) => out.push(text) };
  for (const args of [[], ["--unknown"], ["conformance"], ["a", "b"], ["missing-file.jsonl"], ["--json", "missing-file.jsonl"]]) assert.equal(await main(args, io), 2);
});

test("CLI conformance compares expected diagnostics, including errors", (t) => {
  const directory = temporaryDirectory(t);
  const fixture = path.join(directory, "case");
  mkdirSync(fixture);
  writeFileSync(path.join(fixture, "stream.jsonl"), lines(header()));
  const expected = path.join(fixture, "expected.json");
  writeFileSync(expected, "[]\n");
  const output = run(["conformance", directory, "--json"]);
  assert.equal(output.status, 0);
  assert.equal(JSON.parse(output.stdout).passed, 1);
  writeFileSync(expected, '[{"code":"missing"}]\n');
  const mismatch = run(["conformance", directory]);
  assert.equal(mismatch.status, 1);
  assert.match(mismatch.stdout, /case: expected/);
  const empty = temporaryDirectory(t);
  assert.equal(run(["conformance", empty]).status, 2);
  writeFileSync(path.join(fixture, "second.jsonl"), "");
  assert.equal(run(["conformance", directory]).status, 2);
});
