#!/usr/bin/env node
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

export function readRequirements(specDirectory) {
  const definitions = new Map();
  for (const file of readdirSync(specDirectory).filter((file) => file.endsWith(".md")).sort()) {
    const text = readFileSync(new URL(file, specDirectory), "utf8");
    for (const [, id] of text.matchAll(/\*\*(ASR-\d{3})\*\*/g)) {
      if (definitions.has(id)) throw new Error(`Duplicate definition: ${id}`);
      definitions.set(id, file.replace(/\.md$/, ""));
    }
  }
  const table = readFileSync(new URL("conformance.md", specDirectory), "utf8");
  const rows = [];
  const listed = new Set();
  for (const line of table.split("\n")) {
    if (!/^\|\s*ASR-/.test(line)) continue;
    const match = /^\| (ASR-\d{3}) \| \[[^\]]+\]\(([^)]+)\.md\) \| (.+) \| (schema|semantic|fixture) \|$/.exec(line);
    if (!match) throw new Error(`Invalid requirement row: ${line}`);
    const [, id, page, summary, check] = match;
    if (listed.has(id)) throw new Error(`Duplicate requirement row: ${id}`);
    if (definitions.get(id) !== page) throw new Error(`Definition missing or on a different page: ${id}`);
    listed.add(id);
    rows.push([id, { page, summary, check }]);
  }
  if (!rows.length || rows.length !== definitions.size) throw new Error("Requirement definitions and table do not match.");
  return Object.fromEntries(rows);
}

function main() {
  const requirements = readRequirements(new URL("../../../spec/", import.meta.url));
  const body = "// Generated from spec/conformance.md by scripts/build-requirements.mjs.\nexport const REQUIREMENTS = " + JSON.stringify(requirements, null, 2) + ";\n";
  const target = new URL("../src/requirements.js", import.meta.url);
  const check = process.argv.includes("--check");
  if (check) {
    if (readFileSync(target, "utf8") !== body) throw new Error("requirements.js is stale. Run pnpm run build.");
  } else writeFileSync(target, body);
  console.log(`${Object.keys(requirements).length} requirements ${check ? "checked" : "written"}.`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
