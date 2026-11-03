import { scanJson } from "./jsonl.js";
import { validateWithSchema } from "./schema/validate.js";

export const MANIFEST_SCHEMA = "https://agentsessionrecord.org/schema/v0/manifest.schema.json";

// Compare fractional seconds as text so sub-millisecond receipt times do not
// collapse onto a window boundary through Date's millisecond precision.
function instant(value) {
  if (typeof value !== "string") return;
  const match = /^(.*[Tt]\d{2}:\d{2}:\d{2})(?:\.(\d+))?([Zz]|[+-]\d{2}:\d{2})$/.exec(value);
  if (!match) return;
  const leap = match[1].endsWith(":60");
  const seconds = Date.parse((leap ? match[1].slice(0, -2) + "59" : match[1]) + match[3]) + (leap ? 1000 : 0);
  if (Number.isFinite(seconds)) return { seconds, leap, fraction: match[2] ?? "" };
}

function compare(a, b) {
  if (a.seconds !== b.seconds) return Math.sign(a.seconds - b.seconds);
  if (a.leap !== b.leap) return a.leap ? -1 : 1;
  const length = Math.max(a.fraction.length, b.fraction.length);
  const left = a.fraction.padEnd(length, "0");
  const right = b.fraction.padEnd(length, "0");
  return left < right ? -1 : left > right ? 1 : 0;
}

export function isManifest(input) {
  try { return JSON.parse(Buffer.from(input).toString("utf8"))?.$schema === MANIFEST_SCHEMA; }
  catch { return false; }
}

// A manifest is one JSON document, not a JSONL stream. Its guidance has no
// numbered ASR requirements, including for syntax and duplicate-key diagnostics.
export function validateManifest(input) {
  const diagnostics = [];
  const records = [];
  const error = (code, message, pointer = "") => diagnostics.push({ severity: "error", code, line: 1, pointer, message });
  const warn = (code, message, pointer) => diagnostics.push({ severity: "warning", code, line: 1, pointer, message });
  let raw;
  try { raw = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(Buffer.from(input)); }
  catch { error("invalid-utf8", "Manifest is not valid UTF-8."); }
  if (raw !== undefined) {
    let value;
    try { value = JSON.parse(raw); }
    catch { error("invalid-json", "Manifest is not a JSON document."); }
    if (!diagnostics.length) {
      const { duplicates, numbers } = scanJson(raw);
      for (const pointer of duplicates) error("duplicate-key", "Duplicate object key.", pointer);
      if (!duplicates.length) {
        records.push({ line: 1, value, raw });
        diagnostics.push(...validateWithSchema("manifest", value, numbers).map((problem) => ({ ...problem, line: 1 })));
        const usableTime = (time, pointer) => diagnostics.some((problem) => problem.pointer === pointer) ? undefined : instant(time);
        const start = usableTime(value?.window?.start, "/window/start");
        const end = usableTime(value?.window?.end, "/window/end");
        if (start && end && compare(end, start) <= 0) warn("manifest-window-order", "Window end must be after its start.", "/window/end");
        if (Array.isArray(value?.entries)) value.entries.forEach((entry, index) => {
          if (typeof entry?.status === "string" && !["received", "failed", "unreadable"].includes(entry.status)) {
            warn("manifest-unknown-status", "Unknown receipt status.", `/entries/${index}/status`);
          }
          const pointer = `/entries/${index}/receivedAt`;
          const received = usableTime(entry?.receivedAt, pointer);
          if (start && end && received && (compare(received, start) < 0 || compare(received, end) >= 0)) {
            warn("manifest-receipt-outside-window", "Receipt time must be at or after window start and before window end.", pointer);
          }
        });
      }
    }
  }
  diagnostics.sort((a, b) => a.code.localeCompare(b.code) || a.pointer.localeCompare(b.pointer));
  return { valid: !diagnostics.some((problem) => problem.severity === "error"), kind: "manifest", records, diagnostics };
}
