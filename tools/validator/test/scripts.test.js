import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { checkBlock, checkMarkdown, markdownFiles } from "../scripts/check-doc-examples.mjs";
import { readRequirements } from "../scripts/build-requirements.mjs";
import { header, message, call, annotation, lines, temporaryDirectory } from "./helpers.js";

test("documentation blocks with headers receive stream checks", () => {
  const problems = checkBlock(lines(header(), message(), message()), "jsonl");
  assert.ok(problems.some(({ code }) => code === "duplicate-id"));
  assert.equal(checkBlock(lines(header(), call()), "jsonl").filter(({ severity }) => severity === "error").length, 0);
});

test("excerpts use only record schemas, including annotation excerpts", () => {
  assert.deepEqual(checkBlock(lines(call()), "jsonl"), []);
  assert.deepEqual(checkBlock(lines(annotation({ supersedes: "not-in-excerpt" })), "jsonl"), []);
  assert.ok(checkBlock('{"type":"message","id":"m"}\n', "jsonl").length > 0);
});

test("JSON blocks support full documents, streams and discovery", () => {
  assert.deepEqual(checkBlock(JSON.stringify(header(), null, 2), "json"), []);
  assert.deepEqual(checkBlock(lines(header(), message()), "json"), []);
  assert.deepEqual(checkBlock('{"agent":"codex","exportCommand":["exporter"]}', "json"), []);
  assert.ok(checkBlock('{"agent":"codex","exportCommand":[]}', "json").length > 0);
  assert.ok(checkBlock('{"type":"message","id":"a","id":"b"}', "json").some(({ code }) => code === "duplicate-key"));
  assert.ok(checkBlock('null', "json").length > 0);
  assert.ok(checkBlock('{broken}\n', "json").length > 0);
  assert.ok(checkBlock('{"type":"gap","id":"g","reason":"unknown","count":1e-400}', "json").length > 0);
  const largeHeader = '{\n"type":"session","id":"h","formatVersion":"0.1","agent":{"name":"codex"},"sessionId":"s","producer":{"name":"x","version":"1","method":"native"},"future":1e400\n}';
  assert.deepEqual(checkBlock(largeHeader, "json"), []);
});

test("Markdown checks backtick and tilde fences and reports source lines", () => {
  const source = '# Example\n\n```jsonl\n{"type":"message","id":"m"}\n```\n\n~~~json\n' + JSON.stringify(message()) + '\n~~~\n';
  const output = checkMarkdown(source);
  assert.equal(output.blocks, 2);
  assert.ok(output.diagnostics.every(({ line }) => line === 4));
  assert.equal(checkMarkdown('```json\n```\n').diagnostics.length, 1);
  assert.equal(checkMarkdown('```json\n{}\n').diagnostics.length, 1);
});

test("explicit native examples receive syntax checks without ASR field requirements", () => {
  const native = '```jsonl native\n{"uuid":"native","message":{"content":[]}}\n```\n';
  assert.deepEqual(checkMarkdown(native), { blocks: 1, diagnostics: [] });
  assert.ok(checkMarkdown(native.replace('"uuid":"native"', '"uuid":"native","uuid":"duplicate"')).diagnostics.some(({ code }) => code === "duplicate-key"));
  assert.ok(checkMarkdown('```json native\n{broken}\n```').diagnostics.length > 0);
  assert.ok(checkMarkdown(native.replace("jsonl native", "jsonl")).diagnostics.length > 0);
});

test("Markdown discovery includes MDX but skips generated and installed trees", (t) => {
  const directory = temporaryDirectory(t);
  for (const name of ["site/pages", "node_modules/dependency", ".venv/lib/dependency", "python/package/.venv/lib/dependency", ".mint", "dist", "examples"]) mkdirSync(path.join(directory, name), { recursive: true });
  for (const name of ["site/pages/tour.mdx", "node_modules/dependency/README.md", ".venv/lib/dependency/README.md", "python/package/.venv/lib/dependency/README.md", ".mint/index.md", "dist/output.md", "examples/README.md", "README.md"]) writeFileSync(path.join(directory, name), "");
  assert.deepEqual(markdownFiles(directory).map((file) => path.relative(directory, file)).sort(), ["README.md", "examples/README.md", "site/pages/tour.mdx"]);
});

test("requirement IDs are unique and each table entry has exactly one definition on its page", (t) => {
  const directory = temporaryDirectory(t);
  const spec = pathToFileURL(directory + path.sep);
  const row = '| ASR-001 | [Format](format.md) | JSONL | semantic |\n';
  writeFileSync(new URL("format.md", spec), "**ASR-001** A rule.\n");
  writeFileSync(new URL("conformance.md", spec), row);
  assert.equal(readRequirements(spec)["ASR-001"].check, "semantic");
  writeFileSync(new URL("format.md", spec), "**ASR-001** A rule.\n**ASR-001** Duplicate.\n");
  assert.throws(() => readRequirements(spec), /Duplicate/);
  writeFileSync(new URL("format.md", spec), "**ASR-001** A rule.\n");
  for (const table of [row + row, row.replace("ASR-001", "ASR-002"), row.replace("format.md", "wrong.md"), row.replace("semantic", "retired"), ""]) {
    writeFileSync(new URL("conformance.md", spec), table);
    assert.throws(() => readRequirements(spec));
  }
  writeFileSync(new URL("conformance.md", spec), row);
  writeFileSync(new URL("format.md", spec), "**ASR-001** One.\n**ASR-002** Two.\n");
  assert.throws(() => readRequirements(spec), /do not match/);
  writeFileSync(new URL("format.md", spec), "**ASR-072** New rule.\n**ASR-001** Stable rule.\n");
  writeFileSync(new URL("conformance.md", spec), row.replace("ASR-001", "ASR-072") + row);
  assert.deepEqual(Object.keys(readRequirements(spec)), ["ASR-072", "ASR-001"]);
});
