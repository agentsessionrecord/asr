const decoder = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });
const pointerKey = (key) => key.replace(/~/g, "~0").replace(/\//g, "~1");

// JSON.parse validates syntax first. This iterative scan detects keys that it
// would silently overwrite, including escaped spellings and nested objects.
export function scanJson(text) {
  const stack = [];
  const duplicates = [];
  const numbers = new Map();
  const childPath = () => {
    const top = stack.at(-1);
    return top ? `${top.path}/${top.keys ? pointerKey(top.key ?? "") : top.index}` : "";
  };
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    const top = stack.at(-1);
    if (char === "{") stack.push({ keys: new Set(), expectingKey: true, path: childPath() });
    else if (char === "[") stack.push({ index: 0, path: childPath() });
    else if (char === "}" || char === "]") stack.pop();
    else if (char === ",") {
      if (top.keys) top.expectingKey = true;
      else top.index++;
    } else if (char === '"') {
      let end = i + 1;
      for (; text[end] !== '"'; end++) if (text[end] === "\\") end++;
      if (top?.keys && top.expectingKey) {
        const key = JSON.parse(text.slice(i, end + 1));
        if (top.keys.has(key)) duplicates.push(`${top.path}/${pointerKey(key)}`);
        top.keys.add(key);
        top.key = key;
        top.expectingKey = false;
      }
      i = end;
    } else if (char === "-" || /[0-9]/.test(char)) {
      let end = i + 1;
      while (end < text.length && /[0-9.eE+-]/.test(text[end])) end++;
      numbers.set(childPath(), text.slice(i, end));
      i = end - 1;
    }
  }
  return { duplicates, numbers };
}

export const duplicateKeys = (text) => scanJson(text).duplicates;

export function parseLine(bytes, line) {
  const diagnostics = [];
  const error = (code, message, pointer = "") => diagnostics.push({ severity: "error", requirement: "ASR-001", code, line, pointer, message });
  let raw;
  try { raw = decoder.decode(bytes); }
  catch { error("invalid-utf8", "Line is not valid UTF-8 and was skipped."); return { diagnostics }; }
  if (!raw.trim()) {
    error("blank-line", "Blank line is not a record.");
    return { diagnostics };
  }
  let value;
  try { value = JSON.parse(raw); }
  catch { error("invalid-json", "Line is not valid JSON and was skipped."); return { diagnostics }; }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    error("non-object", "A record must be a JSON object.");
    return { diagnostics };
  }
  const { duplicates, numbers } = scanJson(raw);
  for (const pointer of duplicates) error("duplicate-key", "Duplicate object key. Line was skipped.", pointer);
  return { diagnostics, ...(!duplicates.length ? { record: { line, value, raw, numbers } } : {}) };
}

export const incompleteLine = (line) => ({ severity: "warning", requirement: "ASR-070", code: "incomplete-line", line, pointer: "", message: "Final line has no LF and is deferred until complete." });

export function readJsonl(input) {
  const bytes = Buffer.from(input);
  const records = [];
  const diagnostics = [];
  let start = 0;
  let line = 1;
  while (start < bytes.length) {
    const end = bytes.indexOf(10, start);
    if (end === -1) {
      diagnostics.push(incompleteLine(line));
      break;
    }
    const parsed = parseLine(bytes.subarray(start, end), line++);
    diagnostics.push(...parsed.diagnostics);
    if (parsed.record) records.push(parsed.record);
    start = end + 1;
  }
  return { records, diagnostics, completeLines: line - 1, incomplete: start < bytes.length };
}

// Split bytes, not decoded text: a UTF-8 character or CRLF can cross chunks.
// Accumulate fragments once per line rather than repeatedly copying its prefix.
export async function* byteLines(chunks) {
  let fragments = [];
  let length = 0;
  for await (const input of chunks) {
    const chunk = Buffer.isBuffer(input) ? input : Buffer.from(input);
    let start = 0;
    let end;
    while ((end = chunk.indexOf(10, start)) !== -1) {
      const part = chunk.subarray(start, end);
      const bytes = fragments.length ? Buffer.concat([...fragments, part], length + part.length) : part;
      fragments = [];
      length = 0;
      yield { bytes, complete: true };
      start = end + 1;
    }
    if (start < chunk.length) {
      // Copy the tail so a short fragment cannot retain a large consumed chunk.
      const tail = Buffer.from(chunk.subarray(start));
      fragments.push(tail);
      length += tail.length;
    }
  }
  if (length) yield { bytes: Buffer.concat(fragments, length), complete: false };
}
