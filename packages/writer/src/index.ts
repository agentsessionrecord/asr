import { createHash } from "node:crypto";
import { closeSync, openSync, writeSync } from "node:fs";
import { validateRecord } from "@agent-session/validate";
import type { Session } from "@agent-session/types";

export * from "./privacy.js";
export * from "./references.js";

export type RecordInput = { type: string; id?: string; [key: string]: unknown };
export type SessionHeader = {
  agent: Session["agent"];
  sessionId: string;
  producer: Session["producer"];
  id?: string;
  [key: string]: unknown;
};

/** Stable derived IDs are separate from native IDs supplied through record.id. */
export function deriveId(scope: string, type: string, position: number, collision = 0): string {
  if (!Number.isSafeInteger(position) || position < 0 || !Number.isSafeInteger(collision) || collision < 0) {
    throw new TypeError("ID positions must be non-negative safe integers");
  }
  return "asr-" + createHash("sha256").update(JSON.stringify([scope, type, position, collision])).digest("hex");
}

/** Bigints become strings. Unsafe JS numbers have already lost precision. */
function jsonValue(value: unknown, seen = new Set<object>()): unknown {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "bigint") return String(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value) || Math.abs(value) > Number.MAX_SAFE_INTEGER) {
      throw new TypeError("Use a string or bigint for large native values and finite numbers otherwise");
    }
    return value;
  }
  if (typeof value !== "object" || seen.has(value)) throw new TypeError("Expected acyclic JSON data");
  const proto = Object.getPrototypeOf(value);
  if (!Array.isArray(value) && proto !== Object.prototype && proto !== null) {
    throw new TypeError("Expected plain JSON objects");
  }
  if (Object.getOwnPropertySymbols(value).length) throw new TypeError("Symbol keys are not JSON data");
  seen.add(value);
  try {
    if (Array.isArray(value)) {
      return Array.from(value, (item) => jsonValue(item, seen));
    }
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, jsonValue(item, seen)]));
  } finally {
    seen.delete(value);
  }
}

function checkVcs(record: Record<string, unknown>): void {
  const vcs = record as Record<string, any>;
  if (vcs.parents && "parentCount" in vcs && vcs.parents.length !== vcs.parentCount) {
    throw new TypeError("Parent count must match parents");
  }
  const commits = [vcs.commit, vcs.headBefore, vcs.headAfter, ...(vcs.parents ?? []),
    ...(vcs.rewrites ?? []).flatMap((pair: any) => [pair.from, pair.to]),
    vcs.pr?.headCommit, vcs.pr?.mergeCommit, ...(vcs.pr?.commits ?? [])];
  if (new Set(commits.filter((value) => typeof value === "string").map((value) => value.length)).size > 1) {
    throw new TypeError("Full commit IDs must have the same length");
  }
  if ((vcs.rewrites ?? []).some((pair: any) => pair.from === pair.to)) {
    throw new TypeError("Rewrite endpoints must differ");
  }
}

/** Creates one new UTF-8 stream. Completed records are written synchronously. */
export class Writer {
  #fd: number | undefined;
  #failed = false;
  #ids = new Set<string>();
  #results = new Set<string>();
  #missing = new Set<string>();
  #position = 0;
  #scope: string;
  #copiedThrough: string | undefined;

  constructor(path: string, header: SessionHeader) {
    const value = jsonValue(header) as Record<string, any>;
    if (("type" in value && value.type !== "session") || ("formatVersion" in value && value.formatVersion !== "0.1")) {
      throw new TypeError("A writer requires a version 0.1 session header");
    }
    this.#scope = JSON.stringify([value.agent?.name, value.namespace ?? null, value.sessionId]);
    const record = this.#prepare({ ...value, type: "session", formatVersion: "0.1" });
    this.#copiedThrough = record.parent?.copiedThrough;
    if (this.#copiedThrough === record.id) throw new TypeError("Copied prefix must end after the header");
    this.#fd = openSync(path, "ax", 0o600);
    try {
      this.#write(record);
    } catch (error) {
      closeSync(this.#fd);
      this.#fd = undefined;
      throw error;
    }
  }

  #prepare(value: Record<string, any>): Record<string, any> {
    if (!("id" in value)) {
      let collision = 0;
      do { value.id = deriveId(this.#scope, value.type, this.#position, collision++); } while (this.#ids.has(value.id));
    }
    const diagnostics = validateRecord(value);
    if (diagnostics.length) {
      throw new TypeError(diagnostics.map((problem) => `${problem.pointer}: ${problem.message}`).join("\n"));
    }
    if (this.#ids.has(value.id)) throw new TypeError("Duplicate record ID");
    if (value.type === "tool_result" && value.callId !== undefined && this.#results.has(value.callId)) {
      throw new TypeError("Duplicate result callId");
    }
    if (value.type === "inference" && !("model" in value) && !this.#missing.has("model")) {
      throw new TypeError("Declare model in missing before an inference without a model");
    }
    if (value.type === "vcs") checkVcs(value);
    if (value.type === "approval") {
      if (value.decision === "cancelled" && ("scope" in value || "person" in value)) {
        throw new TypeError("Cancelled approvals have no scope or person");
      }
      if ("person" in value && "by" in value && value.by !== "user") {
        throw new TypeError("A recorded person answers by user");
      }
    }
    return value;
  }

  #write(record: Record<string, any>): string {
    const bytes = Buffer.from(JSON.stringify(record) + "\n", "utf8");
    try {
      let offset = 0;
      while (offset < bytes.length) {
        const count = writeSync(this.#fd!, bytes, offset, bytes.length - offset);
        if (count <= 0) throw new Error("Write made no progress");
        offset += count;
      }
    } catch (error) {
      this.#failed = true;
      throw error;
    }
    this.#position++;
    this.#ids.add(record.id);
    if (record.type === "tool_result" && record.callId !== undefined) this.#results.add(record.callId);
    if (record.type === "session" || record.type === "session_info") {
      for (const loss of record.missing ?? []) this.#missing.add(loss);
    }
    return record.id;
  }

  append(record: RecordInput): string {
    if (this.#fd === undefined || this.#failed) throw new Error("Writer is closed or failed");
    const value = jsonValue(record) as Record<string, any>;
    if (value.type === "session" || value.type === "annotation") {
      throw new TypeError("Append session events only. Annotations require a separate file");
    }
    return this.#write(this.#prepare(value));
  }

  update(fields: { [key: string]: unknown }): string {
    if ("type" in fields) throw new TypeError("update supplies the session_info type");
    return this.append({ ...fields, type: "session_info" });
  }

  close(): void {
    if (this.#fd === undefined) return;
    closeSync(this.#fd);
    this.#fd = undefined;
    if (this.#copiedThrough && !this.#ids.has(this.#copiedThrough)) {
      throw new Error("Copied prefix must end at a record after the header");
    }
  }
}
