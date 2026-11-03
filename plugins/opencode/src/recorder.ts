import { environmentSecrets, redactSecrets, sessionReference } from "@agent-session/writer";
import { HOOK_CONVENTIONS, repositorySnapshot, reasoningPart, logCaptureError, markAgentLoss } from "@agent-session/writer/capture";
import { isAbsolute } from "node:path";
import { Sink } from "./sink.js";
import { snapshot, type Data } from "./privacy.js";

export type Agent = "opencode" | "kilo" | "mimocode";
export const META = HOOK_CONVENTIONS.metadata;
const EXTENSION = HOOK_CONVENTIONS.extension;
const kinds: Data = { bash: "execute", shell: "execute", read: "read", edit: "edit", write: "edit", apply_patch: "edit", glob: "search", grep: "search", webfetch: "fetch", websearch: "search", task: "other" };
const missing = ["reasoning", "usage", "timestamps", "tool_output", "exit_codes", "file_changes", "commits", "subagents", "copies", "model", "approvals", "agent_settings", "tools", "instructions", "message_authorship", "session_user", "hook_outcomes", "approval_decider", "approval_scope", "native_record_ids", "session_lifecycle", "callback_delivery", "nested_tool_calls"];
type State = { sink: Sink; requests: Map<string, Data>; effective: Map<string, unknown>; names: Map<string, string>; messages: Set<string>; mode?: string };
type Observation = { name: string; input: Data; output: Data; ts: string; shortened: boolean };
export interface Options { agent: Agent; directory?: string; content?: "metadata" | "full"; secrets?: string[]; now?: () => string; maxQueue?: number }

export class Recorder {
  private states = new Map<string, State>();
  private disabled = new Set<string>();
  private queue: Observation[] = [];
  private dropped = new Map<string, { ts: string; batch: number }>();
  private batch = 0;
  private scheduled = false;
  private closed = false;
  private now: () => string;
  private full: boolean;
  private secrets: string[];
  constructor(private options: Options) {
    this.now = options.now ?? (() => new Date().toISOString());
    this.full = options.content === "full";
    this.secrets = options.secrets ?? environmentSecrets(process.env);
  }

  observe(name: string, input: Data = {}, output: Data = {}): void {
    if (this.closed || !this.options.directory) return;
    let ts = new Date().toISOString();
    try {
      ts = this.now();
      const session = this.session(name, input);
      if (this.queue.length >= (this.options.maxQueue ?? 256)) { this.loss(session, ts); return; }
      const copied = snapshot({ input, output }, this.full, this.secrets);
      if (this.session(name, copied.value.input) !== session) { this.loss(session, ts); return; }
      this.queue.push({ name, input: copied.value.input, output: copied.value.output, ts, shortened: copied.shortened });
      if (!this.scheduled) {
        this.scheduled = true;
        setImmediate(() => this.flush());
      }
    } catch {
      try {
        const session = this.session(name, input);
        this.loss(session, ts);
      } catch {}
    }
  }

  private loss(session: string | undefined, ts: string): void {
    if (!session) return;
    if (redactSecrets(session, this.secrets) !== session) { markAgentLoss(this.options.directory, this.options.agent); return; }
    if (this.queue.length < (this.options.maxQueue ?? 256)) {
      this.queue.push({ name: "capture.loss", input: { sessionID: session }, output: {}, ts, shortened: false });
      if (!this.scheduled) { this.scheduled = true; setImmediate(() => this.flush()); }
    } else if (this.dropped.size < 64 && !this.dropped.has(session)) this.dropped.set(session, { ts, batch: this.batch });
  }

  private session(name: string, input: Data): string | undefined {
    const event = name === "event" ? input?.event : undefined;
    const data = event?.properties ?? event?.data;
    const id = input?.sessionID ?? data?.sessionID ?? data?.info?.id ?? data?.part?.sessionID;
    return typeof id === "string" && id.length > 0 && id.length < 4096 ? id : undefined;
  }

  flush(): void {
    this.scheduled = false;
    const batch = this.batch++;
    for (const item of this.queue.splice(0)) {
      const sessionID = this.session(item.name, item.input);
      if (!sessionID || this.disabled.has(sessionID)) continue;
      try { this.process(sessionID, item, batch); }
      catch {
        this.states.get(sessionID)?.sink.stop(item.ts);
        this.states.get(sessionID)?.sink.close();
        logCaptureError(this.options.directory);
        this.states.delete(sessionID);
        if (this.disabled.size < 64) this.disabled.add(sessionID);
      }
    }
    // Overflow observations arrived after all items in the full queue.
    for (const [sessionID, loss] of this.dropped) {
      const state = this.states.get(sessionID);
      if (!state) continue;
      try {
        state.sink.append({ type: "session_info", ts: loss.ts, missing: ["dropped_callbacks"] });
        state.sink.append({ type: "gap", ts: loss.ts, reason: "not_recorded", detail: "Callbacks exceeded recorder limits." });
      } catch { state.sink.stop(loss.ts); logCaptureError(this.options.directory); state.sink.close(); this.states.delete(sessionID); if (this.disabled.size < 64) this.disabled.add(sessionID); }
      this.dropped.delete(sessionID);
    }
  }

  private process(sessionID: string, item: Observation, batch: number): void {
    const { name, input, output, ts, shortened } = item;
    const event = name === "event" ? input.event : undefined;
    const type = event?.type;
    const data = event?.properties ?? event?.data ?? {};
    let state = this.states.get(sessionID);
    if (!state) {
      if (this.states.size + this.disabled.size >= 64) return;
      const info = data.info ?? data;
      const header: Data = {
        agent: { name: this.options.agent, ...(type === "session.created" && typeof info.version === "string" ? { version: info.version } : {}) },
        sessionId: sessionID,
        producer: { name: `asr-hooks-${this.options.agent}`, version: "0.1.0", method: "recorder", source: "opencode-plugin-api" },
        missing: [...missing, ...(!this.full ? ["content"] : ["redacted_content"])], extensions: [EXTENSION], ts,
      };
      if (type === "session.created") {
        header.startedAt = ts;
        if (typeof info.directory === "string" && isAbsolute(info.directory)) Object.assign(header, repositorySnapshot(info.directory));
        // parentID alone does not distinguish a subagent from a fork.
        if (typeof info.parentID === "string") {
          header._meta = { [META]: { parentID: info.parentID } };
          header.missing.push("parent_lineage");
        }
      }
      const sink = new Sink(this.options.directory!, header as any);
      state = { sink, requests: new Map(), effective: new Map(), names: new Map(), messages: new Set() };
      this.states.set(sessionID, state);
      if (type !== "session.created") sink.append({ type: "gap", ts, reason: "not_recorded", detail: "Attached without observing session creation. Earlier history is unknown." });
    }
    if (shortened) state.sink.append({ type: "session_info", ts, missing: ["redacted_content"] });
    let sourceIdUsed = false;
    const write = (record: Data) => {
      const sourceId = event?.id;
      const sourceRecord = record.type === "tool_result" || record.type === "approval" || record.type.startsWith(META + "/");
      const useSourceId = sourceRecord && !sourceIdUsed && typeof sourceId === "string" && sourceId.length > 0 && sourceId.length <= 256 && !/[\x00-\x1f\x7f]/.test(sourceId) && !state!.sink.hasId(sourceId);
      if (useSourceId) sourceIdUsed = true;
      state!.sink.append({ ts, ...(useSourceId ? { id: sourceId } : {}), ...(shortened ? { truncated: true } : {}), ...record } as any);
    };
    const earlierLoss = this.dropped.get(sessionID);
    if (earlierLoss && earlierLoss.batch < batch) {
      write({ type: "session_info", ts: earlierLoss.ts, missing: ["dropped_callbacks"] });
      write({ type: "gap", ts: earlierLoss.ts, reason: "not_recorded", detail: "Callbacks exceeded recorder limits." });
      this.dropped.delete(sessionID);
    }
    if (name === "capture.loss") {
      write({ type: "session_info", missing: ["dropped_callbacks"] });
      write({ type: "gap", reason: "not_recorded", detail: "Callbacks exceeded recorder limits or could not be copied." });
      return;
    }
    const call = (id: any, tool?: string, requested?: unknown) => {
      if (typeof id === "string" && typeof tool === "string" && !state!.sink.results.has(id)) state!.names.set(id, tool);
      if (typeof id !== "string" || !id || state!.sink.calls.has(id)) return;
      const record: Data = { type: "tool_call", callId: id };
      if (typeof tool === "string") { record.name = tool; state!.names.set(id, tool); if (kinds[tool]) record.kind = kinds[tool]; }
      if (this.full && requested !== undefined) record._meta = { [META]: { requestedInput: requested } };
      write(record);
    };
    const result = (id: string, status: string, effective: unknown, content?: any, metadata?: Data, error?: any, time?: Data) => {
      if (state!.sink.results.has(id)) return;
      const record: Data = { type: "tool_result", callId: id, status };
      if (this.full && effective !== undefined) record.input = effective;
      if (this.full && content !== undefined) {
        if (typeof content === "string") record.content = [{ type: "text", text: content }];
        else if (Array.isArray(content)) {
          record.content = content.filter((part: Data) => part && typeof part.type === "string").map((part: Data) => part.type === "reasoning" ? reasoningPart(part.text, part.visibility, part.summary) : ["text", "image", "audio", "resource", "resource_link"].includes(part.type) ? part : { type: META + "/content", _meta: { [META]: { native: part } } });
        }
      }
      if (this.full && typeof error === "string") record.error = { message: error };
      if (metadata?.truncated === true) record.truncated = true;
      if (time && Number.isSafeInteger(time.start) && Number.isSafeInteger(time.end) && time.end >= time.start) record.durationMs = time.end - time.start;
      const tool = state!.names.get(id);
      if (this.full && (tool === "bash" || tool === "shell")) {
        const exec: Data = {};
        if (typeof (effective as Data)?.command === "string") exec.command = (effective as Data).command;
        if (typeof (effective as Data)?.workdir === "string" && isAbsolute((effective as Data).workdir)) exec.cwd = (effective as Data).workdir;
        if (Number.isSafeInteger(metadata?.exit)) exec.exitCode = metadata!.exit;
        if (typeof content === "string") exec.output = content;
        if (Object.keys(exec).length) record.exec = exec;
      }
      // Task metadata supplies a child link. Do not infer lineage from output text.
      if (tool === "task" && typeof metadata?.sessionId === "string") record.subagent = { session: sessionReference(this.options.agent, metadata.sessionId) };
      write(record);
      state!.effective.delete(id);
      state!.names.delete(id);
    };
    const mode = (value: unknown) => {
      if (typeof value === "string" && value !== state!.mode) { write({ type: "session_info", agentSettings: { mode: value } }); state!.mode = value; }
    };
    if (name === "tool.execute.before") {
      call(input.callID, input.tool, output.args);
      write({ type: META + "/hook", hook: name, callId: input.callID, ...(typeof output.cancel === "boolean" ? { cancel: output.cancel } : {}) });
    } else if (name === "tool.execute.after") {
      call(input.callID, input.tool);
      if (state.effective.size < 2048 && Object.hasOwn(input, "args")) state.effective.set(input.callID, input.args);
      write({ type: META + "/hook", hook: name, callId: input.callID });
      // The terminal bus item follows all after hooks and supplies final output.
    } else if (name === "v2.before") {
      call(input.id, input.tool, input.input);
      mode(input.agent);
      write({ type: META + "/hook", hook: "tool.execute.before", callId: input.id });
    } else if (name === "v2.after") {
      call(input.id, input.tool);
      if (state.effective.size < 2048 && Object.hasOwn(input, "input")) state.effective.set(input.id, input.input);
      write({ type: META + "/hook", hook: "tool.execute.after", callId: input.id, status: input.status });
    } else if (name === "permission.ask" || name === "v2.permission") {
      write({ type: META + "/hook", hook: name, ...(typeof (output.status ?? input.effect) === "string" ? { observedStatus: output.status ?? input.effect } : {}) });
    } else if (name === "chat.message") mode(input.agent);
    else if (name === "event") {
      if (type === "permission.asked") {
        if (state.requests.size < 2048 && typeof data.id === "string") state.requests.set(data.id, data);
        write({ type: META + "/hook", hook: type, requestId: data.id, ...((data.tool?.callID ?? data.source?.id) ? { callId: data.tool?.callID ?? data.source?.id } : {}) });
      } else if (type === "permission.replied") {
        const request = state.requests.get(data.requestID);
        const decision = data.reply === "reject" ? "denied" : ["once", "always"].includes(data.reply) ? "approved" : undefined;
        if (decision) {
          const record: Data = { type: "approval", decision, native: { reply: data.reply, requestID: data.requestID } };
          const callId = request?.tool?.callID ?? request?.source?.id;
          if (typeof callId === "string") record.callId = callId;
          // Reply events also cover timeouts and cascades. They do not identify a decider.
          if (!record.callId && typeof (request?.permission ?? request?.action) === "string") record.subject = request?.permission ?? request?.action;
          if (data.reply === "once") record.scope = "once";
          write(record);
        }
        state.requests.delete(data.requestID);
      } else if (["session.created", "session.updated", "session.deleted", "session.idle", "session.status", "session.agent.selected", "session.permissions"].includes(type)) {
        write({ type: META + "/hook", hook: type });
        const info = data.info ?? data;
        mode(info.agent);
        if (this.full && typeof info.title === "string") write({ type: "session_info", title: info.title });
        // Idle and deletion are not explicit session-end events.
      } else if (type === "message.part.updated") {
        const part = data.part;
        if (part?.type === "tool") {
          const current = part.state ?? {};
          if (["running", "completed", "error"].includes(current.status)) call(part.callID, part.tool);
          if (current.status === "completed" || current.status === "error") {
            const effective = state.effective.has(part.callID) ? state.effective.get(part.callID) : current.input;
            result(part.callID, current.metadata?.cancelled === true ? "cancelled" : current.status === "error" ? "failed" : "completed", effective, current.output, current.metadata, current.error, current.time);
          }
        } else if (part?.type === "text" && part.time?.end !== undefined && !state.messages.has(part.id)) {
          if (state.messages.size >= 4096) throw new Error("Message limit");
          state.messages.add(part.id);
          // The part alone does not establish role or authorship. Keep it as a source observation.
          write({ type: META + "/text", partId: part.id, ...(this.full && typeof part.text === "string" ? { text: part.text } : {}) });
        }
      } else if (type === "session.tool.input.started") {
        call(data.id, data.name);
      } else if (type === "session.tool.success" || type === "session.tool.failed") {
        call(data.id);
        result(data.id, type.endsWith("success") ? "completed" : "failed", state.effective.get(data.id), data.content, data.metadata, data.error?.message);
      }
    }
    if (state.names.size > 2048) throw new Error("Pending tool limit");
  }

  close(): void {
    if (this.closed) return;
    this.flush();
    this.closed = true;
    for (const state of this.states.values()) state.sink.close();
    this.states.clear();
  }
}
