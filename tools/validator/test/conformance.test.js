import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { readdirSync } from "node:fs";
import path from "node:path";
import { runConformance } from "../src/conformance.js";
import { validateFile } from "../src/index.js";
import { REQUIREMENTS } from "../src/requirements.js";

const root = fileURLToPath(new URL("../../../", import.meta.url));
for (const fixture of runConformance(path.join(root, "conformance/fixtures"))) {
  test(`fixture: ${fixture.name}`, () => {
    assert.deepEqual(fixture.actual, fixture.expected);
    for (const problem of fixture.actual) if (problem.requirement) assert.ok(REQUIREMENTS[problem.requirement]);
  });
}
const examples = path.join(root, "examples");
for (const file of readdirSync(examples, { recursive: true }).filter((file) => /\.(jsonl|json)$/.test(file))) {
  test(`example: ${file}`, () => {
    const output = validateFile(path.join(examples, file));
    assert.equal(output.valid, true, JSON.stringify(output.diagnostics));
    assert.deepEqual(output.diagnostics, []);
  });
}
