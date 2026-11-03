#!/usr/bin/env node
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { readJsonl, scanJson } from "../src/jsonl.js";
import { validate, validateRecord } from "../src/index.js";
import { MANIFEST_SCHEMA, validateManifest } from "../src/manifest.js";

const ignored = new Set(["node_modules", ".venv", ".git", ".mint", "dist"]);
export function markdownFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const filename = path.join(directory, entry.name);
    if (entry.isDirectory() && !ignored.has(entry.name) && !entry.name.startsWith(".test-tmp-")) return markdownFiles(filename);
    return entry.isFile() && /\.(md|mdx)$/i.test(entry.name) ? [filename] : [];
  });
}

export function checkBlock(body, language, native = false) {
  let parsed;
  if (language === "json") {
    let value;
    try { value = JSON.parse(body); }
    catch { return checkBlock(body, "jsonl", native); }
    if (!native && value?.$schema === MANIFEST_SCHEMA) return validateManifest(body).diagnostics;
    const { duplicates, numbers } = scanJson(body);
    if (duplicates.length) return duplicates.map((pointer) => ({ severity: "error", requirement: "ASR-001", code: "duplicate-key", line: 1, pointer, message: "Duplicate object key." }));
    if (native) return [];
    if (typeof value?.agent === "string") return validateRecord(value, "discovery", numbers).map((problem) => ({ ...problem, line: 1 }));
    parsed = { records: [{ line: 1, value, numbers }], diagnostics: [] };
  } else parsed = readJsonl(body);
  if (native) return parsed.diagnostics;
  if (parsed.records[0]?.line === 1 && parsed.records[0].value?.type === "session") {
    if (language === "json") {
      // Whitespace outside strings can be removed without losing numeric spelling.
      const compact = body.replace(/"(?:[^"\\]|\\.)*"|\s+/g, (token) => token.startsWith('"') ? token : "");
      return validate(compact + "\n").diagnostics;
    }
    return validate(body).diagnostics;
  }
  return [
    ...parsed.diagnostics,
    ...parsed.records.flatMap(({ line, value, numbers }) => validateRecord(value, undefined, numbers).map((problem) => ({ ...problem, line }))),
  ];
}

export function checkMarkdown(text) {
  const lines = text.split("\n");
  const diagnostics = [];
  let blocks = 0;
  for (let index = 0; index < lines.length; index++) {
    const open = /^ {0,3}(`{3,}|~{3,})(jsonl?)(?:\s+(native))?\s*$/i.exec(lines[index]);
    if (!open) continue;
    blocks++;
    const start = index + 1;
    const close = new RegExp(`^ {0,3}${open[1][0]}{${open[1].length},}\\s*$`);
    while (++index < lines.length && !close.test(lines[index])) {}
    if (index === lines.length || index === start) {
      diagnostics.push({ severity: "error", line: start, message: "Empty or unclosed JSON example block." });
      continue;
    }
    for (const problem of checkBlock(lines.slice(start, index).join("\n") + "\n", open[2].toLowerCase(), Boolean(open[3]))) {
      diagnostics.push({ ...problem, line: start + problem.line });
    }
  }
  return { blocks, diagnostics };
}

function main() {
  const root = path.resolve(process.argv[2] ?? fileURLToPath(new URL("../../../", import.meta.url)));
  const all = markdownFiles(root);
  const files = all.filter((filename) => {
    const relative = path.relative(root, filename).split(path.sep).join("/");
    return /^(spec|guides|agents|site\/pages|examples|samples)\//.test(relative) || relative === "whitepaper/whitepaper.md" || /^readme\.md$/i.test(path.basename(filename));
  });
  let blocks = 0;
  let errors = 0;
  let warnings = 0;
  for (const file of files) {
    const result = checkMarkdown(readFileSync(file, "utf8"));
    blocks += result.blocks;
    for (const problem of result.diagnostics) {
      if (problem.severity === "warning") warnings++;
      else errors++;
      console.error(`${path.relative(root, file)}:${problem.line}: ${problem.requirement ?? ""} ${problem.pointer ?? ""} ${problem.message}`);
    }
  }
  console.log(`${files.length} Markdown files, ${blocks} JSON/JSONL blocks, ${errors} errors, ${warnings} warnings.`);
  process.exitCode = errors || warnings ? 1 : 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
