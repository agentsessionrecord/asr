import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { validateFile } from "./index.js";

export function diagnosticSummary({ severity, requirement, code, line, pointer }) {
  return { severity, ...(requirement ? { requirement } : {}), code, line, pointer };
}

export function runConformance(directory) {
  const cases = readdirSync(directory, { withFileTypes: true }).filter((entry) => entry.isDirectory()).sort((a, b) => a.name.localeCompare(b.name));
  if (!cases.length) throw new Error("No conformance cases found.");
  return cases.map(({ name }) => {
    const folder = path.join(directory, name);
    const files = readdirSync(folder).filter((file) => file.endsWith(".jsonl") || file.endsWith(".manifest.json"));
    if (files.length !== 1) throw new Error(`${name}: expected exactly one session, annotations or manifest input.`);
    const expected = JSON.parse(readFileSync(path.join(folder, "expected.json"), "utf8"));
    const actual = validateFile(path.join(folder, files[0])).diagnostics.map(diagnosticSummary);
    return { name, passed: isDeepStrictEqual(actual, expected), expected, actual };
  });
}
