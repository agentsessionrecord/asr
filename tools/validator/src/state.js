import { CORE_TYPES } from "./schema/build.js";
import { validateWithSchema } from "./schema/validate.js";

const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const append = (map, key, line) => {
  const lines = map.get(key);
  if (lines) lines.push(line);
  else map.set(key, [line]);
};

// Shared by buffered and streaming APIs. Only relationship keys and physical
// lines outlive accept(). No message, input, output, metadata or numeric map does.
export class ValidationState {
  constructor({ filename = "", mode = "auto", summary = false } = {}) {
    if (!["auto", "session", "annotations"].includes(mode)) throw new Error(`Unknown validation mode: ${mode}`);
    this.kind = mode === "auto" ? (filename.endsWith(".annotations.jsonl") ? "annotations" : undefined) : mode;
    this.summary = summary;
    this.diagnostics = [];
    this.errors = 0;
    this.warnings = 0;
    this.counts = {};
    this.recordCount = 0;
    this.ids = new Map();
    this.calls = new Map();
    this.results = new Map();
    this.approvals = new Map();
    this.inferences = new Set();
    this.inferenceRefs = new Map();
    this.copyBoundaries = new Map();
    this.unknownModels = [];
    this.modelMissing = false;
    this.hasHeader = false;
  }

  add(problem) {
    if (problem.severity === "error") this.errors++;
    else this.warnings++;
    const key = `${problem.severity}:${problem.code}`;
    this.counts[key] = (this.counts[key] ?? 0) + 1;
    if (!this.summary) this.diagnostics.push(problem);
  }

  error(requirement, code, line, pointer, message) {
    this.add({ severity: "error", requirement, code, line, pointer, message });
  }

  warn(code, line, pointer, message) {
    this.add({ severity: "warning", requirement: "ASR-070", code, line, pointer, message });
  }

  accept({ line, value: record, numbers }) {
    this.kind ??= record.type === "annotation" ? "annotations" : "session";
    const annotations = this.kind === "annotations";
    this.recordCount++;
    if (line === 1 && record.type === "session") this.hasHeader = true;
    for (const problem of validateWithSchema(annotations ? "annotation" : "record", record, numbers)) this.add({ ...problem, line });
    if (!annotations && record.type === "session" && line !== 1) this.error("ASR-002", "extra-header", line, "/type", "The session header belongs only on line 1.");
    if (!annotations && record.type === "annotation") this.error("ASR-061", "annotation-in-session", line, "/type", "Annotations belong in a separate file.");
    else if (!annotations && typeof record.type === "string" && !CORE_TYPES.includes(record.type)) this.warn("unknown-type", line, "/type", "Unknown record type. Only the envelope is checked.");
    if (typeof record.id === "string" && this.ids.has(record.id)) this.error("ASR-007", "duplicate-id", line, "/id", `Record ID duplicates line ${this.ids.get(record.id)}.`);
    if (annotations && typeof record.supersedes === "string" && !this.ids.has(record.supersedes)) {
      this.error("ASR-064", "supersedes-not-earlier", line, "/supersedes", "Correction must name an earlier annotation in this file.");
    }
    if (typeof record.id === "string" && (!annotations || record.type === "annotation") && !this.ids.has(record.id)) this.ids.set(record.id, line);
    if ((!annotations && record.type === "vcs") || (annotations && record.kind === "vcs")) this.checkVcs(annotations ? record.data : record, line, annotations ? "/data" : "");
    if (annotations) return;

    if (["session", "session_info"].includes(record.type) && Array.isArray(record.missing) && record.missing.includes("model")) this.modelMissing = true;
    if (record.type === "inference") {
      if (typeof record.id === "string") this.inferences.add(record.id);
      if (!Object.hasOwn(record, "model")) this.unknownModels.push(line);
    }
    if (typeof record.inferenceId === "string") append(this.inferenceRefs, record.inferenceId, line);
    if (record.type === "tool_call") {
      if (typeof record.callId === "string") append(this.calls, record.callId, line);
      if (!Object.hasOwn(record, "name")) this.warn("missing-tool-name", line, "/name", "Tool call has no recorded name.");
    }
    if (record.type === "tool_result") {
      if (typeof record.callId === "string") {
        if (this.results.has(record.callId)) this.error("ASR-026", "duplicate-result", line, "/callId", `Result callId duplicates line ${this.results.get(record.callId)[0]}.`);
        append(this.results, record.callId, line);
      } else this.warn("unpaired-result", line, "/callId", "Result has no unique matching tool call.");
    }
    if (record.type === "approval" && typeof record.callId === "string") append(this.approvals, record.callId, line);
    if (record.type === "session") {
      const through = record.parent?.copiedThrough;
      if (typeof through === "string") append(this.copyBoundaries, through, line);
      if (Array.isArray(record.extensions)) record.extensions.forEach((extension, index) => {
        if (typeof extension === "string") this.warn("unknown-extension", line, `/extensions/${index}`, "Unknown extension. Its semantics are ignored.");
      });
    }
  }

  checkVcs(vcs, line, path) {
    if (!isObject(vcs)) return;
    const commits = [vcs.commit, vcs.headBefore, vcs.headAfter,
      ...(Array.isArray(vcs.parents) ? vcs.parents : []),
      ...(Array.isArray(vcs.rewrites) ? vcs.rewrites.flatMap((pair) => [pair?.from, pair?.to]) : []),
      vcs.pr?.headCommit, vcs.pr?.mergeCommit,
      ...(Array.isArray(vcs.pr?.commits) ? vcs.pr.commits : [])];
    const lengths = new Set(commits.filter((id) => typeof id === "string" && /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/.test(id)).map((id) => id.length));
    if (lengths.size > 1) this.error("ASR-032", "mixed-commit-lengths", line, path, "Full commit IDs within one VCS payload must have the same length.");
    if (Array.isArray(vcs.parents) && Number.isInteger(vcs.parentCount) && vcs.parents.length !== vcs.parentCount) this.error("ASR-032", "parent-count", line, `${path}/parentCount`, "Parent count must equal the parents array length.");
    if (Array.isArray(vcs.rewrites)) vcs.rewrites.forEach((pair, index) => {
      if (isObject(pair) && typeof pair.from === "string" && pair.from === pair.to) this.error("ASR-032", "identical-rewrite", line, `${path}/rewrites/${index}`, "Rewrite endpoints must differ.");
    });
  }

  finish({ completeLines, incomplete }) {
    this.kind ??= "session";
    if (this.kind === "session") {
      if ((completeLines > 0 || !incomplete) && !this.hasHeader) this.error("ASR-002", "missing-header", 1, "/type", "Line 1 must be a session record.");
      for (const [id, lines] of this.results) if (this.calls.get(id)?.length !== 1) {
        for (const line of lines) this.warn("unpaired-result", line, "/callId", "Result has no unique matching tool call.");
      }
      for (const [id, lines] of this.approvals) if (this.calls.get(id)?.length !== 1) {
        for (const line of lines) this.warn("unpaired-approval", line, "/callId", "Approval has no unique matching tool call.");
      }
      for (const [id, lines] of this.calls) if (lines.length !== 1 || !this.results.has(id)) {
        for (const line of lines) this.warn("call-without-result", line, "/callId", "Call has no uniquely paired result. Its outcome is unknown.");
      }
      for (const [id, lines] of this.inferenceRefs) if (!this.inferences.has(id)) {
        for (const line of lines) this.warn("unresolved-inference", line, "/inferenceId", "No matching inference record in this file.");
      }
      for (const [id, lines] of this.copyBoundaries) if (!(this.ids.get(id) > 1)) {
        for (const line of lines) this.error("ASR-041", "copied-through", line, "/parent/copiedThrough", "Copied prefix must end at a record after the header in this file.");
      }
      if (!this.modelMissing) for (const line of this.unknownModels) this.error("ASR-035", "missing-model-loss", line, "/model", "An inference without a model requires model in the session's missing losses.");
    }
    this.diagnostics.sort((a, b) => a.line - b.line || a.code.localeCompare(b.code) || a.pointer.localeCompare(b.pointer));
    return { valid: this.errors === 0, kind: this.kind, recordCount: this.recordCount, errors: this.errors, warnings: this.warnings, counts: this.counts, ...(!this.summary ? { diagnostics: this.diagnostics } : {}) };
  }
}
