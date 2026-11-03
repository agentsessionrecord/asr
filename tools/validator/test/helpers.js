import { mkdtempSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { validate } from "../src/index.js";

export const header = (fields = {}) => ({ type: "session", id: "header", formatVersion: "0.1", agent: { name: "com.example.agent" }, sessionId: "run-1", producer: { name: "example-export", version: "1", method: "native" }, ...fields });
export const message = (fields = {}) => ({ type: "message", id: "message", role: "user", content: [], ...fields });
export const call = (fields = {}) => ({ type: "tool_call", id: "call", callId: "c1", name: "read", ...fields });
export const result = (fields = {}) => ({ type: "tool_result", id: "result", callId: "c1", status: "completed", ...fields });
export const approval = (fields = {}) => ({ type: "approval", id: "approval", callId: "c1", decision: "approved", ...fields });
export const change = (fields = {}) => ({ type: "file_change", id: "edit", path: "src/main.py", op: "modify", status: "applied", ...fields });
export const vcs = (fields = {}) => ({ type: "vcs", id: "commit", action: "commit", status: "completed", evidence: "observed", ...fields });
export const inference = (fields = {}) => ({ type: "inference", id: "model", model: { requested: "example-model" }, ...fields });
export const annotation = (fields = {}) => ({ type: "annotation", id: "a1", session: "com.example.agent:run-1", kind: "title", at: "2026-10-27T09:00:00Z", source: { name: "indexer" }, data: { title: "Parser fix" }, ...fields });
export const lines = (...records) => records.map((record) => JSON.stringify(record)).join("\n") + "\n";
export const session = (...records) => validate(lines(header(), ...records));
export const commit = "a".repeat(40);
export const otherCommit = "b".repeat(40);
export function temporaryDirectory(t) {
  const directory = mkdtempSync(fileURLToPath(new URL("../.test-tmp-", import.meta.url)));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  return directory;
}
