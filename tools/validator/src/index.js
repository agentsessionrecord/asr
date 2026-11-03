import { readFileSync } from "node:fs";
import { validateWithSchema } from "./schema/validate.js";
import { readJsonl } from "./jsonl.js";
import { isManifest, validateManifest } from "./manifest.js";
import { ValidationState } from "./state.js";
export { validateManifest } from "./manifest.js";
export { validateStream, validateFileStream, validateDirectory } from "./stream.js";

// Excerpts receive only envelope and per-type schema checks.
export function validateRecord(record, kind = record?.type === "annotation" ? "annotation" : "record", numbers) {
  return validateWithSchema(kind, record, numbers);
}

export function validate(input, { filename = "", mode = "auto" } = {}) {
  if (mode === "manifest" || (mode === "auto" && (filename.endsWith(".manifest.json") || isManifest(input)))) return validateManifest(input);
  const state = new ValidationState({ filename, mode });
  const parsed = readJsonl(input);
  for (const problem of parsed.diagnostics) state.add(problem);
  for (const record of parsed.records) state.accept(record);
  const { valid, kind, diagnostics } = state.finish(parsed);
  return { valid, kind, records: parsed.records.map(({ numbers, ...record }) => record), diagnostics };
}

export function validateFile(filename) {
  return validate(readFileSync(filename), { filename });
}
