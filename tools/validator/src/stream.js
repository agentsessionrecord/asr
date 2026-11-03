import { createReadStream } from "node:fs";
import { opendir } from "node:fs/promises";
import path from "node:path";
import { byteLines, incompleteLine, parseLine } from "./jsonl.js";
import { MANIFEST_SCHEMA, validateManifest } from "./manifest.js";
import { ValidationState } from "./state.js";

// Small lookahead supports a leading manifest $schema on stdin without ever
// loading an ordinary session to discover its kind. Explicit manifest mode and
// the filename suffix support documents with a different property order.
async function sniff(chunks) {
  const iterator = chunks[Symbol.asyncIterator]?.() ?? chunks[Symbol.iterator]();
  const pending = [];
  let size = 0;
  try {
    while (size < 4096) {
      const next = await iterator.next();
      if (next.done) break;
      const bytes = Buffer.isBuffer(next.value) ? next.value : Buffer.from(next.value);
      pending.push(bytes);
      size += bytes.length;
    }
  } catch (error) {
    await iterator.return?.();
    throw error;
  }
  const prefix = Buffer.concat(pending.map((bytes) => bytes.subarray(0, 4096)), Math.min(size, 4096)).toString("utf8");
  const match = /^\s*\{\s*"\$schema"\s*:\s*"([^"]+)"/.exec(prefix);
  return {
    manifest: match?.[1] === MANIFEST_SCHEMA,
    chunks: (async function* () {
      try {
        yield* pending;
        while (true) {
          const next = await iterator.next();
          if (next.done) break;
          yield next.value;
        }
      } finally { await iterator.return?.(); }
    })(),
  };
}

function manifestReport(result, summary) {
  const counts = {};
  let errors = 0;
  let warnings = 0;
  for (const problem of result.diagnostics) {
    if (problem.severity === "error") errors++;
    else warnings++;
    const key = `${problem.severity}:${problem.code}`;
    counts[key] = (counts[key] ?? 0) + 1;
  }
  return { valid: result.valid, kind: result.kind, recordCount: result.records.length, errors, warnings, counts, ...(!summary ? { diagnostics: result.diagnostics } : {}) };
}

export async function validateStream(input, { filename = "", mode = "auto", summary = false } = {}) {
  if (!["auto", "session", "annotations", "manifest"].includes(mode)) throw new Error(`Unknown validation mode: ${mode}`);
  let chunks = input;
  let manifest = mode === "manifest" || (mode === "auto" && filename.endsWith(".manifest.json"));
  if (mode === "auto" && !manifest && !filename.endsWith(".annotations.jsonl")) {
    const detected = await sniff(chunks);
    manifest = detected.manifest;
    chunks = detected.chunks;
  }
  if (manifest) {
    const parts = [];
    for await (const chunk of chunks) parts.push(Buffer.from(chunk));
    return manifestReport(validateManifest(Buffer.concat(parts)), summary);
  }
  const state = new ValidationState({ filename, mode, summary });
  let line = 1;
  let incomplete = false;
  for await (const part of byteLines(chunks)) {
    if (!part.complete) {
      incomplete = true;
      state.add(incompleteLine(line));
      continue;
    }
    const parsed = parseLine(part.bytes, line++);
    for (const problem of parsed.diagnostics) state.add(problem);
    if (parsed.record) state.accept(parsed.record);
  }
  return state.finish({ completeLines: line - 1, incomplete });
}

export async function validateFileStream(filename, options = {}) {
  return validateStream(createReadStream(filename), { ...options, filename });
}

async function* files(directory) {
  const entries = await opendir(directory);
  for await (const entry of entries) {
    const filename = path.join(directory, entry.name);
    if (entry.isDirectory()) yield* files(filename);
    else if (entry.isFile() && (entry.name.endsWith(".jsonl") || entry.name.endsWith(".manifest.json"))) yield filename;
  }
}

// Consumers receive and release one file's diagnostics at a time. Symlinked
// entries are skipped so traversal cannot loop or validate a target twice.
export async function* validateDirectory(directory, options = {}) {
  for await (const file of files(directory)) {
    try { yield { file, ...await validateFileStream(file, options) }; }
    catch (error) { yield { file, error: error.message }; }
  }
}
