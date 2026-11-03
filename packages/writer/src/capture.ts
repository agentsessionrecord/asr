import { appendFileSync, closeSync, existsSync, fstatSync, lstatSync, mkdirSync, mkdtempSync, openSync, readFileSync, readSync, renameSync, rmSync, statSync, writeFileSync, writeSync } from "node:fs";
import { join } from "node:path";
import { repositorySnapshot } from "./repository.js";
import { validate } from "@agent-session/validate";
import { deriveId, Writer, type SessionHeader } from "./index.js";

import conventions from "./hook-conventions.json" with { type: "json" };
export const HOOK_CONVENTIONS = conventions;
export { repositorySnapshot } from "./repository.js";

export function privateCaptureFile(path: string): number {
  const stat = lstatSync(path);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.uid !== process.getuid?.() || (stat.mode & 0o077)) throw new Error("Unsafe capture file");
  return stat.size;
}

export function privateCaptureDirectory(directory: string): void {
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  const stat = lstatSync(directory);
  if (!stat.isDirectory() || stat.isSymbolicLink() || stat.uid !== process.getuid?.() || (stat.mode & 0o077)) throw new Error("Unsafe capture directory");
}

/** Diagnostics contain fixed codes only, never source text or exception messages. */
export function logCaptureError(directory: string | undefined): void {
  if (!directory) return;
  try {
    privateCaptureDirectory(directory);
    const path = join(directory, ".recorder-errors.log");
    if (existsSync(path)) privateCaptureFile(path);
    if (!existsSync(path) || statSync(path).size < 65536) appendFileSync(path, "capture_error\n", { mode: 0o600 });
  } catch {}
}

export function markCaptureLoss(path: string): void {
  try { writeFileSync(path, "", { flag: "wx", mode: 0o600 }); } catch {}
}

export function markAgentLoss(directory: string | undefined, agent: string): void {
  if (!directory || !/^[a-z0-9-]+$/.test(agent)) return;
  try { privateCaptureDirectory(directory); markCaptureLoss(join(directory, `.${agent}.dropped`)); logCaptureError(directory); } catch {}
}

/** PID and age recover killed hooks. A short wait absorbs parallel callbacks. */
export function acquireCaptureLock(path: string, staleAfterMs = 10000): { stale: boolean; release(): void } | undefined {
  const deadline = Date.now() + 100;
  let stale = false;
  while (true) {
    let fd: number | undefined;
    try {
      fd = openSync(path, "wx", 0o600);
      writeFileSync(fd, JSON.stringify({ pid: process.pid, createdAt: Date.now() }));
      const owner = fstatSync(fd);
      closeSync(fd); fd = undefined;
      return { stale, release() {
        try {
          const current = lstatSync(path);
          if (current.ino === owner.ino && current.dev === owner.dev) rmSync(path);
        } catch {}
      } };
    } catch (error: any) {
      if (fd !== undefined) { closeSync(fd); try { rmSync(path); } catch {} }
      if (error.code !== "EEXIST") throw error;
      try {
        const stat = lstatSync(path);
        if (stat.isSymbolicLink() || stat.uid !== process.getuid?.() || (stat.mode & 0o077)) throw new Error("Unsafe capture lock");
        const metadata = stat.isDirectory() ? join(path, "owner.json") : path;
        let owner: any;
        try { owner = JSON.parse(readFileSync(metadata, "utf8")); } catch {}
        const pid = typeof owner === "number" ? owner : owner?.pid;
        let dead = false;
        if (Number.isSafeInteger(pid) && pid > 0) {
          try { process.kill(pid, 0); } catch (error: any) { if (error.code === "ESRCH") dead = true; }
        }
        const createdAt = Number.isFinite(owner?.createdAt) ? owner.createdAt : stat.mtimeMs;
        if (dead || Date.now() - createdAt > staleAfterMs) {
          const current = lstatSync(path);
          if (current.ino === stat.ino && current.dev === stat.dev && current.mtimeMs === stat.mtimeMs) {
            rmSync(path, { recursive: stat.isDirectory() }); stale = true; continue;
          }
        }
      } catch (error: any) { if (error.code !== "ENOENT") throw error; }
      if (Date.now() >= deadline) return undefined;
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 5);
    }
  }
}

/** Read only the bounded header when checking ownership of an existing stream. */
export function captureHeader(path: string): Record<string, any> {
  privateCaptureFile(path);
  const fd = openSync(path, "r");
  try {
    const bytes = Buffer.alloc(65536);
    const count = readSync(fd, bytes, 0, bytes.length, 0);
    const end = bytes.subarray(0, count).indexOf(10);
    if (end < 0) throw new Error("Missing bounded capture header");
    return JSON.parse(bytes.subarray(0, end).toString("utf8"));
  } finally { closeSync(fd); }
}

/** Seal only a valid, LF-terminated stream. Existing bytes never change. */
export function sealCapture(path: string, ts: string, detail: string, loss = "capture_stopped"): boolean {
  try {
    privateCaptureFile(path);
    const bytes = readFileSync(path);
    if (bytes.at(-1) !== 10) return false;
    const checked = validate(bytes, { mode: "session" });
    if (!checked.valid) return false;
    const records = checked.records.map(record => record.value);
    const header = records[0];
    const scope = JSON.stringify([header.agent.name, header.namespace ?? null, header.sessionId]);
    const ids = new Set(records.map(record => record.id));
    const rows = [{ type: "gap", reason: "not_recorded", detail, ts }, { type: "session_info", missing: [loss], ts }].map((row, index) => {
      let collision = 0, id;
      do { id = deriveId(scope, row.type, records.length + index, collision++); } while (ids.has(id));
      ids.add(id);
      return { ...row, id };
    });
    appendFileSync(path, rows.map(row => JSON.stringify(row) + "\n").join(""));
    return true;
  } catch { return false; }
}

export type CaptureState = { position: number; size: number; [key: string]: any };
export interface CaptureOptions {
  directory: string; agent: string; sessionId: string; path: string; statePath: string;
  maxStream?: number; lockPath?: string; ts: string; header: SessionHeader; initial: CaptureState; maxState: number;
  /** Returning undefined on a fresh stream holds the header and saves state only. */
  project(state: CaptureState, fresh: boolean): any[] | undefined;
}

/** Incremental state and append-only transactions shared by command hooks. */
export function captureSession(options: CaptureOptions): boolean {
  const { directory, agent, path, statePath, ts } = options;
  const loss = path + ".dropped", sealed = path + ".sealed";
  let lock: ReturnType<typeof acquireCaptureLock>, stage: string | undefined;
  let committed = false, directoryReady = false, owned = false;
  const begun = Date.now();
  try {
    privateCaptureDirectory(directory);
    directoryReady = true;
    lock = acquireCaptureLock(options.lockPath ?? path + ".lock");
    if (!lock) { markCaptureLoss(loss); logCaptureError(directory); return false; }
    if (existsSync(sealed)) return false;
    const fresh = !existsSync(path);
    let state = options.initial;
    if (!fresh) {
      const header = captureHeader(path);
      if (header.type !== "session" || header.agent?.name !== options.header.agent.name || header.sessionId !== options.sessionId ||
        ![options.header.producer.name, "asr-hook-recorder", "asr-gemini-qwen-hooks"].includes(header.producer?.name)) return false;
      owned = true;
      try {
        if (privateCaptureFile(statePath) > options.maxState) throw new Error("Oversized state");
        state = JSON.parse(readFileSync(statePath, "utf8"));
        state.size ??= state.bytes;
        if (state.captureVersion !== 1) throw new Error("Unsupported capture state");
        if (!Number.isSafeInteger(state.position) || state.position < 1 || !Number.isSafeInteger(state.size) || state.size < 1 || privateCaptureFile(path) !== state.size) throw new Error("Inconsistent state");
        if (state.stopped || state.size >= (options.maxStream ?? 64 * 1024 * 1024)) throw new Error("Capture limit");
      } catch {
        sealCapture(path, ts, "Capture stopped after a storage inconsistency or capture limit.");
        markCaptureLoss(sealed); logCaptureError(directory); return false;
      }
    } else if (existsSync(statePath)) {
      if (privateCaptureFile(statePath) > options.maxState) throw new Error("Oversized state");
      state = JSON.parse(readFileSync(statePath, "utf8"));
      if (state.captureVersion !== 1 || state.headerPending !== true || state.position !== 1 || state.size !== 0) throw new Error("State without stream");
    }
    state.captureVersion = 1;
    stage = mkdtempSync(join(directory, ".transaction-"));
    if (fresh && options.header.startedAt && options.header.cwd) {
      Object.assign(options.header, repositorySnapshot(options.header.cwd));
    }
    const projected = options.project(state, fresh);
    if (projected === undefined) {
      if (!fresh || state.position !== 1 || state.size !== 0) throw new Error("Only an unwritten header can be held");
      state.headerPending = true;
      const bytes = JSON.stringify(state);
      if (Buffer.byteLength(bytes) > options.maxState) throw new Error("Oversized state");
      if (lock.stale) markCaptureLoss(loss);
      const checkpoint = join(stage, "checkpoint");
      writeFileSync(checkpoint, bytes, { mode: 0o600 });
      renameSync(checkpoint, statePath);
      committed = true;
      return true;
    }
    delete state.headerPending;
    const pending = [loss, join(directory, `.${agent}.dropped`)];
    let dropped = lock.stale;
    for (const [index, marker] of pending.entries()) {
      if (!existsSync(marker)) continue;
      privateCaptureFile(marker);
      renameSync(marker, join(stage, `dropped-${index}`)); dropped = true;
    }
    let records: any[] = [];
    if (dropped) records.push({ type: "gap", reason: "not_recorded", ts, detail: "A recorder receipt was dropped during contention, stale lock recovery, or input limits." }, { type: "session_info", ts, missing: [HOOK_CONVENTIONS.losses.dropped] });
    records.push(...projected);
    const staged = join(stage, "events");
    const writer = new Writer(staged, options.header);
    try {
      for (const record of records) {
        writer.append({ ...record, id: deriveId(JSON.stringify([options.header.agent.name, options.header.namespace ?? null, options.sessionId]), record.type, state.position++) });
      }
    } finally { writer.close(); }
    const bytes = readFileSync(staged);
    const append = fresh ? bytes : bytes.subarray(bytes.indexOf(10) + 1);
    if (state.size + append.length > (options.maxStream ?? 64 * 1024 * 1024)) {
      if (!fresh) sealCapture(path, ts, "Capture stopped at the stream size limit.");
      markCaptureLoss(sealed); return false;
    }
    state.size += append.length;
    if ("bytes" in state) state.bytes = state.size;
    if (Buffer.byteLength(JSON.stringify(state)) > options.maxState) {
      if (!fresh) sealCapture(path, ts, "Capture stopped at the saved state size limit.");
      markCaptureLoss(sealed); return false;
    }
    if (Date.now() - begun > 650) {
      if (!fresh) sealCapture(path, ts, "Capture stopped at the recorder deadline.");
      markCaptureLoss(sealed); return false;
    }
    const fd = openSync(path, fresh ? "ax" : "a", 0o600);
    owned = true;
    try {
      if (fstatSync(fd).size !== state.size - append.length) throw new Error("Concurrent append");
      let offset = 0;
      while (offset < append.length) {
        const count = writeSync(fd, append, offset, append.length - offset);
        if (count <= 0) throw new Error("Write made no progress");
        offset += count;
      }
    } finally { closeSync(fd); }
    owned = true;
    const checkpoint = join(stage, "checkpoint");
    writeFileSync(checkpoint, JSON.stringify(state), { mode: 0o600 });
    renameSync(checkpoint, statePath);
    if (state.stopped) markCaptureLoss(sealed);
    committed = true;
    return true;
  } catch {
    if (lock && owned && existsSync(path)) {
      sealCapture(path, ts, "Capture stopped after a recorder error."); markCaptureLoss(sealed);
    }
    logCaptureError(directory); return false;
  } finally {
    if (!committed && directoryReady) markCaptureLoss(loss);
    if (stage) { try { rmSync(stage, { recursive: true, force: true }); } catch { logCaptureError(directory); } }
    lock?.release();
  }
}

/** No visibility claim without source evidence. Empty or withheld text is omitted. */
export function reasoningPart(text?: unknown, visibility?: string, summary?: unknown): Record<string, unknown> {
  if (visibility === "encrypted" || visibility === "omitted") return { type: "reasoning", visibility };
  if (Array.isArray(summary)) {
    const values = summary.filter((item): item is string => typeof item === "string");
    return values.some(item => item !== "") ? { type: "reasoning", visibility: "summary", summary: values } : { type: "reasoning", visibility: "omitted" };
  }
  if (typeof text !== "string" || text === "") return { type: "reasoning", visibility: "omitted" };
  if (visibility === "summary") return { type: "reasoning", visibility, summary: [text] };
  return { type: "reasoning", text, ...(visibility ? { visibility } : {}) };
}
