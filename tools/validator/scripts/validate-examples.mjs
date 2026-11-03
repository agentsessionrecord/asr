#!/usr/bin/env node
import { readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { validateFile } from "../src/index.js";

const directory = fileURLToPath(new URL("../../../examples/", import.meta.url));
const files = readdirSync(directory, { recursive: true }).filter((file) => /\.(jsonl|json)$/.test(file)).sort();
if (!files.length) throw new Error("No example streams found.");
let errors = 0;
let warnings = 0;
for (const file of files) {
  const result = validateFile(path.join(directory, file));
  for (const problem of result.diagnostics) {
    if (problem.severity === "warning") { warnings++; continue; }
    errors++;
    console.error(`${file}:${problem.line}: ${problem.requirement} ${problem.pointer} ${problem.message}`);
  }
}
console.log(`${files.length} example files, ${errors} errors, ${warnings} warnings.`);
process.exitCode = errors || warnings ? 1 : 0;
