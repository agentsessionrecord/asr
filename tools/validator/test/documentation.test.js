import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { markdownFiles, checkMarkdown } from "../scripts/check-doc-examples.mjs";
import { validate } from "../src/index.js";

const root = new URL("../../../", import.meta.url);
const read = (file) => readFileSync(new URL(file, root), "utf8");
const blocks = (file, native = false) => [...read(file).matchAll(new RegExp("```jsonl" + (native ? " native" : "") + "\\n([\\s\\S]*?)\\n```", "g"))]
  .map((match) => match[1].split("\n").map((line) => JSON.parse(line)));

test("home and paper use unchanged tour records with all local links", () => {
  const tour = blocks("site/pages/get-started/quick-tour.mdx").slice(0, 5).flat();
  const full = new Map(tour.map((record) => [record.id, record]));
  assert.equal(full.size, tour.length);
  // The home page shows the tour's edit record on its own.
  const [home] = blocks("site/pages/index.mdx");
  assert.deepEqual(home, [full.get("change")]);
  for (const [file, count] of [["whitepaper/whitepaper.md", 6]]) {
    const [excerpt] = blocks(file);
    assert.equal(excerpt.length, count);
    assert.deepEqual(excerpt, tour.filter((record) => excerpt.some(({ id }) => record.id === id)));
    assert.deepEqual(validate(excerpt.map((r) => JSON.stringify(r)).join("\n") + "\n").diagnostics, []);
    const calls = new Set(excerpt.filter(({ type }) => type === "tool_call").map(({ callId }) => callId));
    for (const record of excerpt) if (record.callId) assert.ok(calls.has(record.callId));
  }
  assert.deepEqual(read("examples/coding-session.jsonl").trim().split("\n").map(JSON.parse), tour);
});

test("all four native examples produce valid streams with exact tool inputs and links", () => {
  for (const agent of ["claude-code", "codex", "gemini-cli", "opencode"]) {
    const file = `agents/${agent}.md`;
    assert.deepEqual(checkMarkdown(read(file)).diagnostics, []);
    const [native] = blocks(file, true);
    const [stream] = blocks(file);
    assert.ok(native.length >= 3);
    assert.equal(stream[0].agent.name, agent);
    assert.ok(stream[0].missing.length > 0);
    const call = stream.find(({ type }) => type === "tool_call");
    const result = stream.find(({ type }) => type === "tool_result");
    const edit = stream.find(({ type }) => type === "file_change");
    assert.equal(result.callId, call.callId);
    assert.equal(edit.callId, call.callId);
    assert.equal(stream.filter(({ type }) => type === "tool_result").length, 1);
    if (agent === "claude-code") {
      const source = native[1].message.content[0];
      assert.equal(call.callId, source.id);
      assert.deepEqual(call.input, source.input);
      assert.deepEqual(edit.edits, [{ oldText: source.input.old_string, newText: source.input.new_string }]);
      assert.deepEqual(stream.find(({ type }) => type === "inference").usage, { inputTokens: 10, outputTokens: 5 });
    } else if (agent === "codex") {
      assert.equal(call.inputText, native[1].payload.input);
      assert.equal(result.content[0].text, native[2].payload.output);
      assert.equal(native[3].payload.success, true);
      assert.equal(edit.status, "applied");
    } else if (agent === "gemini-cli") {
      const source = native[2].toolCalls[0];
      assert.deepEqual(call.input, source.args);
      assert.equal(edit.before.text, source.resultDisplay.originalContent);
      assert.equal(edit.after.text, source.resultDisplay.newContent);
      assert.deepEqual(stream.find(({ type }) => type === "inference").usage, { inputTokens: 10, outputTokens: 5 });
    } else {
      const source = native[2].data.state;
      assert.deepEqual(call.input, source.input);
      assert.equal(edit.patch, source.metadata.diff);
      assert.deepEqual(stream.find(({ type }) => type === "inference").usage, { inputTokens: 12, cacheReadTokens: 2, outputTokens: 8, reasoningTokens: 3 });
    }
  }
});

test("documentation streams have no dangling causal call references", () => {
  for (const directory of ["spec", "guides", "agents", "site/pages"]) {
    for (const filename of markdownFiles(fileURLToPath(new URL(directory, root)))) {
      const text = readFileSync(filename, "utf8");
      for (const match of text.matchAll(/```jsonl\n([\s\S]*?)\n```/g)) {
        const records = match[1].split("\n").map(JSON.parse);
        if (records[0]?.type !== "session") continue;
        const calls = new Set(records.filter(({ type }) => type === "tool_call").map(({ callId }) => callId));
        for (const record of records) if (record.callId) assert.ok(calls.has(record.callId), `${filename}: ${record.id}`);
      }
    }
  }
});
