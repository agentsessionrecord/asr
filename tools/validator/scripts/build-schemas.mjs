#!/usr/bin/env node
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { AGENT_NAMES, buildSchemas, SCHEMA_FILES } from "../src/schema/build.js";

const repo = new URL("../../../", import.meta.url);
const names = JSON.parse(readFileSync(new URL("agents/agents.json", repo), "utf8")).map(({ name }) => name);
if (JSON.stringify(names) !== JSON.stringify(AGENT_NAMES)) throw new Error("Update AGENT_NAMES in src/schema/build.js to match agents/agents.json.");
const directory = new URL("schema/v0/", repo);
const check = process.argv.includes("--check");
if (!check) mkdirSync(directory, { recursive: true });
for (const file of readdirSync(directory)) {
  if (file.endsWith(".schema.json") && !Object.values(SCHEMA_FILES).includes(file)) throw new Error(`Unexpected schema: ${file}`);
}
for (const [name, schema] of Object.entries(buildSchemas())) {
  const target = new URL(SCHEMA_FILES[name], directory);
  const body = JSON.stringify(schema, null, 2) + "\n";
  if (check) {
    if (readFileSync(target, "utf8") !== body) throw new Error(`${SCHEMA_FILES[name]} is stale. Run pnpm run build.`);
  } else writeFileSync(target, body);
}
console.log(`${Object.keys(SCHEMA_FILES).length} schemas ${check ? "checked" : "written"}.`);
