import { acquireCaptureLock, captureHeader, logCaptureError, markCaptureLoss, privateCaptureDirectory, privateCaptureFile, sealCapture } from "@agent-session/writer/capture";
import { createHash } from "node:crypto";
import { closeSync, existsSync, lstatSync, openSync, readFileSync, unlinkSync, writeSync } from "node:fs";
import { join } from "node:path";
import { Writer, deriveId, type RecordInput, type SessionHeader } from "@agent-session/writer";
import { validate, validateRecord } from "@agent-session/validate";

/** The library creates new streams. This adapter also resumes an intact stream under a process lock. */
export class Sink {
  private writer?: Writer;
  private fd?: number;
  private lock?: ReturnType<typeof acquireCaptureLock>;
  private consumingLoss = false;
  private agentLoss: string;
  private position = 0;
  private scope: string;
  private ids = new Set<string>();
  readonly results = new Set<string>();
  readonly calls = new Set<string>();
  readonly path: string;
  private lockPath: string;

  constructor(directory: string, header: SessionHeader) {
    privateCaptureDirectory(directory);
    this.scope = JSON.stringify([header.agent.name, header.namespace ?? null, header.sessionId]);
    this.path = join(directory, header.agent.name + "-" + createHash("sha256").update(header.sessionId).digest("hex") + ".jsonl");
    this.lockPath = this.path + ".lock";
    this.agentLoss = join(directory, `.${header.agent.name}.dropped`);
    let owned = false;
    try {
      // In-process adapters hold this lock for their entire attachment.
      this.lock = acquireCaptureLock(this.lockPath, Infinity);
      if (!this.lock) throw new Error("Capture lock unavailable");
      if (existsSync(this.path + ".sealed")) throw new Error("Capture sealed");
      if (this.lock.stale) markCaptureLoss(this.path + ".dropped");
      if (!existsSync(this.path)) {
        this.writer = new Writer(this.path, header);
        owned = true;
        this.ids.add(typeof header.id === "string" ? header.id : deriveId(this.scope, "session", 0));
        this.position = 1;
        return;
      }
      const saved = captureHeader(this.path);
      if (saved.type !== "session" || saved.sessionId !== header.sessionId || saved.agent?.name !== header.agent.name ||
        ![header.producer.name, "asr-opencode-recorder"].includes(saved.producer?.name)) throw new Error("Foreign stream");
      owned = true;
      if (saved.producer.name !== header.producer.name) throw new Error("Older capture conventions");
      const stat = lstatSync(this.path);
      if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 16 * 1024 * 1024) throw new Error("Unsafe or oversized existing stream");
      const bytes = readFileSync(this.path);
      if (bytes.at(-1) !== 10) throw new Error("Incomplete existing stream");
      const checked = validate(bytes, { mode: "session" });
      if (!checked.valid) throw new Error("Invalid existing stream");
      const records = checked.records.map(record => record.value);
      const first = records[0];
      if (first?.type !== "session" || first.formatVersion !== "0.1" || first.sessionId !== header.sessionId || first.agent?.name !== header.agent.name || first.producer?.name !== header.producer.name) throw new Error("Foreign stream");
      owned = true;
      for (const [index, record] of records.entries()) {
        if (validateRecord(record).length || this.ids.has(record.id) || (index > 0 && record.type === "session")) throw new Error("Invalid existing stream");
        this.ids.add(record.id);
        if (record.type === "tool_call") this.calls.add(record.callId);
        if (record.type === "tool_result" && typeof record.callId === "string") {
          if (this.results.has(record.callId)) throw new Error("Duplicate existing result");
          this.results.add(record.callId);
        }
      }
      this.position = records.length;
      this.fd = openSync(this.path, "a", 0o600);
      const receipt = typeof header.ts === "string" ? { ts: header.ts } : {};
      this.append({ type: "session_info", ...receipt, missing: [...(header.missing as string[] ?? []), "capture_restart"] });
      this.append({ type: "gap", ...receipt, reason: "not_recorded", detail: "Recorder restarted. Events between attachments are unknown." });
    } catch (error) {
      markCaptureLoss(this.path + ".dropped");
      if (owned && this.lock && existsSync(this.path)) this.stop(typeof header.ts === "string" ? header.ts : new Date().toISOString());
      logCaptureError(directory);
      this.close();
      throw error;
    }
  }

  append(record: RecordInput): void {
    if (this.position >= 100_000) throw new Error("Session record limit");
    for (const loss of [this.path + ".dropped", this.agentLoss]) {
      if (this.consumingLoss || !existsSync(loss)) continue;
      privateCaptureFile(loss);
      this.consumingLoss = true;
      try {
        this.append({ type: "gap", ...(typeof record.ts === "string" ? { ts: record.ts } : {}), reason: "not_recorded", detail: "A recorder callback was lost during lock contention, stale lock recovery, or input limits." });
        this.append({ type: "session_info", missing: ["dropped_callbacks"] });
        unlinkSync(loss);
      } finally { this.consumingLoss = false; }
    }
    if (record.type === "tool_result" && typeof record.callId === "string" && this.results.has(record.callId)) return;
    if (this.writer) this.ids.add(this.writer.append(record));
    else {
      if (this.fd === undefined) throw new Error("Closed sink");
      let collision = 0;
      let id = record.id;
      if (id === undefined) {
        do { id = deriveId(this.scope, record.type, this.position, collision++); } while (this.ids.has(id));
      }
      if (this.ids.has(id)) throw new Error("Duplicate resumed record ID");
      const value = { ...record, id };
      if (validateRecord(value).length) throw new Error("Invalid resumed record");
      const bytes = Buffer.from(JSON.stringify(value) + "\n");
      let offset = 0;
      while (offset < bytes.length) {
        const written = writeSync(this.fd, bytes, offset, bytes.length - offset);
        if (written <= 0) throw new Error("Write made no progress");
        offset += written;
      }
      this.ids.add(id);
    }
    this.position++;
    if (record.type === "tool_call" && typeof record.callId === "string") this.calls.add(record.callId);
    if (record.type === "tool_result" && typeof record.callId === "string") this.results.add(record.callId);
  }

  hasId(id: string): boolean { return this.ids.has(id); }

  close(): void {
    try { this.writer?.close(); } catch {}
    this.writer = undefined;
    if (this.fd !== undefined) { try { closeSync(this.fd); } catch {} this.fd = undefined; }
    this.lock?.release();
    this.lock = undefined;
  }

  stop(ts: string): void {
    if (this.lock && !existsSync(this.path + ".sealed")) {
      sealCapture(this.path, ts, "Capture stopped after a recorder error or capacity limit.");
      markCaptureLoss(this.path + ".sealed");
    }
  }
}
