// Draft 2020-12 schemas. Keep objects and enums open for future fields and values.
export const AGENT_NAMES = "amp antigravity astrbot auggie claude-code cline codebuddy codex continue copilot-cli crush cursor deepagents deepseek-harness devin droid firebender forgecode fx gemini-cli goose grok-build hermes junie kilo kimi-code kiro lingma mimocode mistral-vibe mux nanoclaw openclaw opencode openhands pi qoder qwen-code roo-code rovodev shelley t3-code tabnine warp xum zed".split(" ");
export const SCHEMA_FILES = {
  record: "agent-session.schema.json",
  annotation: "annotation.schema.json",
  discovery: "discovery.schema.json",
  manifest: "manifest.schema.json",
};
export const CORE_TYPES = ["session", "session_info", "message", "tool_call", "tool_result", "approval", "file_change", "vcs", "inference", "gap"];
const base = "https://agentsessionrecord.org/schema/v0/";
const draft = "https://json-schema.org/draft/2020-12/schema";
const str = { type: "string" };
const uint = { type: "integer", minimum: 0 };
const duration = { type: "number", minimum: 0 };
const nonempty = { type: "string", minLength: 1 };
const sha256 = { type: "string", pattern: "^[0-9a-f]{64}$" };
const ref = (name) => ({ $ref: `#/$defs/${name}` });
const array = (items) => ({ type: "array", items });
const rule = (id, schema) => ({ ...schema, "x-asr": `ASR-${String(id).padStart(3, "0")}` });
const object = (properties, required = []) => ({ type: "object", properties, ...(required.length ? { required } : {}) });
const some = (...names) => ({ anyOf: names.map((name) => ({ required: [name] })) });
const exclusive = (...names) => ({ not: { required: names } });
const nullable = (schema) => schema.type
  ? { ...schema, type: [schema.type, "null"] }
  : { anyOf: [schema, { type: "null" }] };
const when = (field, value, then) => ({ if: { properties: { [field]: { const: value } }, required: [field] }, then });
const dnsLabel = "[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?";
const dns = `${dnsLabel}(?:\\.${dnsLabel})+`;
const vendorType = { if: { properties: { type: { type: "string", pattern: "/" } }, required: ["type"] }, then: rule(17, object({ type: { type: "string", pattern: `^${dns}/[^/\\s]+$` } })) };
const agent = `(?:${AGENT_NAMES.join("|")}|${dns})`;
// Encoded bytes must form valid UTF-8. Raw Unicode is allowed by ASR-011.
const continuation = "(?:%[89AB][0-9A-F])";
const escaped = `(?:%[0-7][0-9A-F]|%(?:C[2-9A-F]|D[0-9A-F])${continuation}|%E0%[AB][0-9A-F]${continuation}|%E[1-CEF]${continuation}{2}|%ED%[89][0-9A-F]${continuation}|%F0%[9AB][0-9A-F]${continuation}{2}|%F[1-3]${continuation}{3}|%F4%8[0-9A-F]${continuation}{2})`;
const component = `(?:${escaped}|[^%:#\\x00-\\x20\\x7F-\\x9F])+`;
const fragment = `(?:(?!%(?:[01][0-9A-F]|7F)|%C2%[89][0-9A-F])${escaped}|[^%:#\\x00-\\x20\\x7F-\\x9F]){1,256}`;

export function buildSchemas() {
  const modelSettings = object({ reasoningEffort: str, maxOutputTokens: uint, temperature: { type: "number" }, serviceTier: str });
  const defs = {
    RecordId: rule(7, { type: "string", minLength: 1, maxLength: 256, pattern: "^[^\\x00-\\x1F\\x7F-\\x9F]+$" }),
    AgentName: rule(10, { type: "string", pattern: `^${agent}$` }),
    SessionRef: rule(11, { type: "string", pattern: `^${agent}:${component}(?::${component})?(?:#${fragment})?$` }),
    SessionOnlyRef: rule(11, { type: "string", pattern: `^${agent}:${component}(?::${component})?$` }),
    Timestamp: rule(6, { type: "string", format: "date-time", pattern: "^[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt]" }),
    AbsolutePath: rule(12, { type: "string", pattern: "^(?:/|[A-Za-z]:[/\\\\]|\\\\\\\\[^\\\\]+\\\\[^\\\\]+)" }),
    Path: rule(12, { type: "string", pattern: "^(?:/[\\s\\S]*|[A-Za-z]:[/\\\\][\\s\\S]*|\\\\\\\\[^\\\\]+\\\\[^\\\\]+[\\s\\S]*|[^\\\\]*)$" }),
    Meta: rule(17, { type: "object", propertyNames: { pattern: `^${dns}$` } }),
    Commit: rule(31, { type: "string", pattern: "^(?:[0-9a-f]{40}|[0-9a-f]{64})$" }),
    CopiedFrom: rule(40, { ...object({ session: ref("SessionOnlyRef"), record: ref("RecordId") }), ...some("session", "record") }),
    Parent: rule(40, object({ session: ref("SessionOnlyRef"), kind: str, callId: str, record: ref("RecordId"), role: str, copiedThrough: ref("RecordId") }, ["session", "kind"])),
    Repos: array(rule(19, object({ path: ref("Path"), remote: str, branch: str, head: ref("Commit") }, ["path"]))),
    Identity: rule(19, { ...object({ id: nonempty, email: nonempty, name: nonempty, source: str }), ...some("id", "email", "name") }),
    DerivedFrom: rule(60, object({ sha256 }, ["sha256"])),
    ExternalSandbox: rule(72, nullable(object({ kind: str, source: str, native: {} }))),
    AgentSettings: rule(20, object({ mode: nullable(str), approval: {}, sandbox: {},
      asks: rule(72, nullable(str)), externalSandbox: ref("ExternalSandbox"), modelSettings: ref("ConfiguredModelSettings") })),
    Model: rule(35, { ...object({ provider: str, id: str, requested: str }), ...some("id", "requested") }),
    ModelSettings: rule(35, modelSettings),
    ConfiguredModelSettings: rule(20, nullable(object(Object.fromEntries(Object.entries(modelSettings.properties).map(([name, schema]) => [name, nullable(schema)]))))),
    Tools: rule(74, array(object({ name: str, description: str, inputSchema: {}, source: str }, ["name"]))),
    Usage: rule(36, object(Object.fromEntries(["inputTokens", "cacheReadTokens", "cacheWriteTokens", "outputTokens", "reasoningTokens"].map((name) => [name, uint])))),
    SessionUsage: rule(20, { allOf: [ref("Usage"), object({ includesSubagents: { type: "boolean" } })] }),
    Cost: rule(37, object({ amount: { type: "number" }, currency: { type: "string", pattern: "^[A-Z]{3}$" }, source: str }, ["amount", "currency"])),
    Error: object({ message: str, code: {} }),
    FileState: rule(30, {
      ...object({ text: str, objectId: str, objectIdType: str }),
      allOf: [
        { if: { properties: { objectIdType: { const: "git-blob-sha1" } } }, then: object({ objectId: { type: "string", pattern: "^[0-9a-f]{40}$" } }) },
        { if: { properties: { objectIdType: { enum: ["git-blob-sha256", "sha256"] } }, required: ["objectIdType"] }, then: object({ objectId: { type: "string", pattern: "^[0-9a-f]{64}$" } }) },
      ],
    }),
    PullRequest: rule(31, {
      ...object({ url: str, repository: str, number: { type: "integer", minimum: 1 }, state: str, headCommit: ref("Commit"), mergeCommit: ref("Commit"), commits: array(ref("Commit")) }),
      anyOf: [{ required: ["url"] }, { required: ["repository", "number"] }],
    }),
    Vcs: rule(31, {
      ...object({
        action: str, status: str, evidence: str, callId: str, actor: str, repo: ref("AbsolutePath"),
        commit: ref("Commit"), commitPrefix: { type: "string", pattern: "^[0-9a-f]{7,39}$" }, subject: str,
        parents: array(ref("Commit")), parentCount: uint, headBefore: ref("Commit"), headAfter: ref("Commit"),
        rewrites: array(object({ from: ref("Commit"), to: ref("Commit") }, ["from", "to"])),
        branch: str, remote: str, pr: ref("PullRequest"),
      }, ["action", "status", "evidence"]),
      allOf: [exclusive("commit", "commitPrefix"), exclusive("callId", "actor")],
    }),
  };
  const base64 = { type: "string", contentEncoding: "base64", format: "asr-base64" };
  defs.ContentPart = rule(13, {
    ...object({ type: str, author: str, origin: str }, ["type"]),
    allOf: [
      vendorType,
      when("type", "text", object({ text: str }, ["text"])),
      ...["image", "audio"].map((type) => when("type", type, object({ mimeType: str, data: base64 }, ["mimeType"]))),
      when("type", "resource_link", object({ uri: str, name: str, title: str, description: str, mimeType: str, size: uint }, ["uri", "name"])),
      when("type", "resource", object({ resource: { ...object({ uri: str, mimeType: str, text: str, blob: base64 }, ["uri"]), ...some("text", "blob") } }, ["resource"])),
      when("type", "reasoning", {
        ...object({ text: str, summary: array(str), visibility: str }),
        allOf: [when("visibility", "encrypted", rule(15, { not: { anyOf: [{ required: ["text"] }, { required: ["summary"] }] } }))],
      }),
    ],
  });
  defs.Content = rule(13, array(ref("ContentPart")));
  defs.Envelope = rule(6, object({
    type: str, id: ref("RecordId"), ts: ref("Timestamp"), turnId: str, inferenceId: ref("RecordId"),
    copiedFrom: ref("CopiedFrom"), truncated: { type: "boolean" }, _meta: ref("Meta"),
  }, ["type", "id"]));
  const records = {
    session: rule(19, object({
      formatVersion: rule(2, { const: "0.1" }), agent: object({ name: ref("AgentName"), version: str }, ["name"]),
      sessionId: rule(10, { type: "string", minLength: 1 }), namespace: rule(10, { type: "string", minLength: 1 }), producer: object({ name: str, version: str, method: str, source: str }, ["name", "version", "method"]),
      startedAt: ref("Timestamp"), endedAt: ref("Timestamp"), title: str, cwd: ref("AbsolutePath"), repos: ref("Repos"),
      user: ref("Identity"), derivedFrom: ref("DerivedFrom"), parent: ref("Parent"), missing: array(str), extensions: array(str),
    }, ["formatVersion", "agent", "sessionId", "producer"])),
    session_info: rule(20, {
      ...object({ title: str, endedAt: ref("Timestamp"), repos: ref("Repos"), usage: ref("SessionUsage"), cost: ref("Cost"), agentSettings: ref("AgentSettings"), tools: ref("Tools"), missing: rule(57, array(str)) }),
      ...some("title", "endedAt", "repos", "usage", "cost", "agentSettings", "tools", "missing"),
    }),
    message: rule(21, object({ role: str, content: ref("Content"), author: str, person: ref("Identity"), origin: str, phase: str, status: str, from: ref("SessionOnlyRef") }, ["role", "content"])),
    tool_call: rule(23, {
      ...object({
        callId: str, name: str, kind: str, input: {}, inputText: str, requestedBy: str, parentCallId: str,
        locations: array(object({ path: ref("Path"), line: { type: "integer", minimum: 1 } }, ["path"])),
        subagent: object({ session: ref("SessionOnlyRef"), role: str, description: str }),
      }, ["callId"]),
      ...exclusive("input", "inputText"),
    }),
    tool_result: rule(25, { ...object({
      callId: str, status: str, content: ref("Content"), error: ref("Error"), durationMs: duration,
      input: {}, inputText: rule(76, str),
      exec: object({ command: { type: ["string", "array"], items: str }, cwd: ref("AbsolutePath"), exitCode: { type: "integer" }, signal: str, stdout: str, stderr: str, output: str }),
      subagent: object({ session: ref("SessionOnlyRef") }, ["session"]),
    }, ["status"]), allOf: [rule(76, exclusive("input", "inputText"))] }),
    approval: rule(73, object({ callId: str, decision: str, by: str, scope: str, subject: str, person: ref("Identity"), native: {} }, ["decision"])),
    file_change: rule(27, {
      ...object({
        path: ref("Path"), op: str, oldPath: ref("Path"), status: str, callId: str, actor: str,
        before: ref("FileState"), after: ref("FileState"), patch: str,
        edits: array(object({ oldText: str, newText: str }, ["oldText", "newText"])), baseCommit: ref("Commit"),
      }, ["path", "op", "status"]),
      ...exclusive("patch", "edits"),
      allOf: [exclusive("callId", "actor"), ...["move", "copy"].map((op) => when("op", op, { required: ["oldPath"] }))],
    }),
    vcs: ref("Vcs"),
    inference: rule(35, object({ model: ref("Model"), settings: ref("ModelSettings"), usage: ref("Usage"), cost: ref("Cost"), stopReason: str, durationMs: duration, error: ref("Error") })),
    gap: rule(39, object({ reason: str, count: uint, detail: str }, ["reason"])),
  };
  for (const [type, shape] of Object.entries(records)) defs[`record.${type}`] = shape;
  const record = {
    $schema: draft, $id: base + SCHEMA_FILES.record, title: "Agent Session Record 0.1 record",
    allOf: [
      ref("Envelope"),
      ...CORE_TYPES.map((type) => when("type", type, ref(`record.${type}`))),
      // A future core name is unfamiliar, not invalid. A vendor name has a slash.
      vendorType,
    ],
    $defs: defs,
  };
  const shared = (name) => ({ $ref: record.$id + `#/$defs/${name}` });
  const payloads = {
    summary: object({ text: str, model: {} }, ["text"]),
    outcome: object({ status: str, commit: shared("Commit"), revertedBy: shared("Commit"), pr: shared("PullRequest") }, ["status"]),
    test: object({ status: str, commit: shared("Commit"), name: str, url: str }, ["status"]),
    vcs: shared("Vcs"),
    title: object({ title: str }, ["title"]),
  };
  const annotation = {
    $schema: draft, $id: base + SCHEMA_FILES.annotation, title: "Agent Session Record 0.1 annotation",
    ...rule(62, object({
      type: { const: "annotation" }, id: shared("RecordId"), session: shared("SessionRef"), kind: str,
      at: rule(62, { ...defs.Timestamp }), source: object({ name: str, version: str }, ["name"]), data: {}, supersedes: shared("RecordId"),
    }, ["type", "id", "session", "kind", "at", "source", "data"])),
    allOf: Object.entries(payloads).map(([kind, shape]) => when("kind", kind, rule(63, object({ data: shape })))),
  };
  const discovery = {
    $schema: draft, $id: base + SCHEMA_FILES.discovery, title: "Agent Session Record discovery file",
    ...object({
      agent: shared("AgentName"), namespace: str, exportCommand: { ...array(str), minItems: 1 },
      nativePaths: array(str), formatVersions: array({ type: "string", pattern: "^[0-9]+\\.[0-9]+$" }),
      supportsDeletionHook: { type: "boolean" }, _meta: shared("Meta"),
    }, ["agent"]),
  };
  // The collection guide adds no requirements. Its independent schema has no ASR
  // requirement labels and needs no session schema to resolve definitions.
  const timestamp = { type: "string", format: "date-time", pattern: "^[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt]" };
  const digest = object({ sha256 }, ["sha256"]);
  const manifest = {
    $schema: draft, $id: base + SCHEMA_FILES.manifest, title: "ASR collection manifest",
    ...object({
      $schema: { const: base + SCHEMA_FILES.manifest },
      collector: object({ name: nonempty, version: nonempty }, ["name", "version"]),
      machine: nonempty,
      window: object({ start: timestamp, end: timestamp }, ["start", "end"]),
      previousManifest: { anyOf: [digest, { type: "null" }] },
      entries: array({
        ...object({
          session: { type: "string", pattern: `^${agent}:${component}(?::${component})?$` },
          sha256, byteLength: uint, receivedAt: timestamp, uploader: nonempty,
          producer: object({ method: str }, ["method"]), replaces: digest, status: str, reason: str,
        }, ["receivedAt", "uploader", "status"]),
        allOf: [
          when("status", "received", { required: ["session", "sha256", "byteLength", "producer"] }),
          when("status", "unreadable", { required: ["sha256", "byteLength"] }),
          { if: { properties: { status: { not: { const: "received" } } }, required: ["status"] }, then: { required: ["reason"] } },
        ],
      }),
    }, ["$schema", "collector", "machine", "window", "previousManifest", "entries"]),
  };
  const schemas = { record, annotation, discovery, manifest };
  // In ECMA regexes, $ also matches before a final newline. Shapes need the
  // actual end of the string, including IDs and hashes supplied by JSON escapes.
  function anchor(node) {
    if (!node || typeof node !== "object") return;
    if (node.pattern?.endsWith("$")) node.pattern = node.pattern.slice(0, -1) + "(?![\\s\\S])";
    Object.values(node).forEach(anchor);
  }
  anchor(schemas);
  return schemas;
}
