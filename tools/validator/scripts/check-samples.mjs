#!/usr/bin/env node
import { createHash } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { validateFileStream } from "../src/index.js";
import { readJsonl, scanJson } from "../src/jsonl.js";

const directory = fileURLToPath(new URL("../../../samples/", import.meta.url));
let streams = 0;
let records = 0;
let warnings = 0;
for (const { name: agent } of readdirSync(directory, { withFileTypes: true }).filter((entry) => entry.isDirectory())) {
  const folder = path.join(directory, agent);
  const readme = readFileSync(path.join(folder, "README.md"), "utf8");
  const hashes = new Map([...readme.matchAll(/^\| `([^`]+)` \| `([a-f0-9]{64})` \|$/gm)].map((match) => [match[1], match[2]]));
  const dataFiles = readdirSync(folder, { recursive: true }).filter((file) => /\.(jsonl|json)$/.test(file));
  if (hashes.size !== dataFiles.length) throw new Error(`${agent}: hash inventory differs from data files.`);
  for (const file of dataFiles) {
    const filename = path.join(folder, file);
    const bytes = readFileSync(filename);
    if (createHash("sha256").update(bytes).digest("hex") !== hashes.get(file.split(path.sep).join("/"))) throw new Error(`${agent}/${file}: SHA-256 mismatch.`);
    if (file.startsWith("asr" + path.sep) || path.basename(file) === "asr.jsonl") {
      const output = await validateFileStream(filename, { summary: true });
      if (!output.valid) throw new Error(`${agent}/${file}: ${JSON.stringify(output.counts)}`);
      streams++;
      records += output.recordCount;
      warnings += output.warnings;
    } else if (file.endsWith(".jsonl")) {
      if (readJsonl(bytes).diagnostics.length) throw new Error(`${agent}/${file}: invalid native JSONL.`);
    } else {
      const text = bytes.toString("utf8");
      JSON.parse(text);
      if (scanJson(text).duplicates.length) throw new Error(`${agent}/${file}: duplicate native JSON keys.`);
    }
  }
}
if (!streams) throw new Error("No ASR samples found.");
console.log(`${streams} ASR samples, ${records} records, 0 errors, ${warnings} warnings. Native JSON and file digests checked.`);
