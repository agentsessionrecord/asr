---
title: Records
description: The ten core record types and their fields.
sidebar:
  order: 3
---

Every record includes the [envelope](format.md#envelope). The tables below add fields for each type. R means required, O means optional and C means conditional. Times use RFC 3339. All listed enums are open. The examples are record excerpts unless they include a session header.

## `session`

The first line identifies the session and how it was recorded.

| Field | Req | Meaning |
|---|---|---|
| `formatVersion` | R | `"0.1"` |
| `agent` | R | Object with required `name` and optional `version` |
| `sessionId` | R | Non-empty native session ID string, verbatim |
| `namespace` | O | Non-empty installation namespace string when native session IDs repeat |
| `producer` | R | Object with required `name`, `version` and `method`, and optional `source` |
| `user` | O | Person who ran the session, using the identity shape below |
| `derivedFrom` | O | Object with required `sha256`, the digest of the exact source ASR file bytes, as defined in [Safety](missing-data.md#safety) |
| `startedAt`, `endedAt` | O | Session times under the [time rules](format.md#envelope) |
| `title` | O | Recorded title |
| `cwd` | O | Absolute working directory at the start |
| `repos` | O | Array of repositories, each with required `path` and optional `remote`, `branch` and `head` |
| `parent` | O | Parent or predecessor, defined in [Sessions](sessions.md#parent) |
| `missing` | O | Array of strings naming known losses, defined in [Missing data](missing-data.md#known-losses) |
| `extensions` | O | Array of extension names in use |

**ASR-019** A `session` MUST use these field shapes, including the required agent and producer fields. Every supplied `user` or `person` object MUST contain at least one of `id`, `email` or `name`, and each of those fields MUST be a non-empty string when present. Producers MUST take each identity from a real source and MUST NOT guess it. Readers MUST NOT use `user` as proof of prompt or commit authorship. A recorded repository `head` MUST be the full commit ID at the start, and a repository `remote` MUST contain no credentials.

`producer.method` is `native` when the agent writes or exports ASR, `converter` when software converts an existing file, or `recorder` when software observes a live connection or hooks. `producer.source` names the native format read or, for a recorder, the API or connection observed, such as `anthropic-messages` or `openai-responses`. Repository branches and HEADs describe the start of the session when recorded, not the state at export time.

The shared identity shape is used by `session.user`, `message.person` and `approval.person`. Use `source` to say where the identity came from.

| Field | Req | Meaning |
|---|---|---|
| `id` | O | Non-empty string with a stable account or directory ID |
| `email` | O | Non-empty string with the person's email address |
| `name` | O | Non-empty string with the person's recorded name |
| `source` | O | String naming the identity source, as described below |

The known sources are `agent_account` for the account signed in to the agent, `git` for repository or user Git configuration, `os` for the operating-system user, and `configured` for an identity set by whoever runs the converter or exporter. The set is open.

Readers use `user` as a grouping and access label. Message `author` still says who wrote each message. The label does not establish who typed a prompt or made a commit. Identity fields are personal data, so the [safety rules](missing-data.md#safety) apply. Teams and departments can be joined from a company directory, as described in the [company guide](../guides/organizations.md).

```jsonl
{"type":"session","id":"header","formatVersion":"0.1","agent":{"name":"com.example.agent","version":"1.0"},"sessionId":"session-7","producer":{"name":"example-converter","version":"1.0","method":"converter","source":"example-jsonl"},"cwd":"/work/app","repos":[{"path":"/work/app","remote":"https://example.com/team/app.git","branch":"fix/empty"}]}
```

## `session_info`

This record adds facts while a writer appends to the stream. It also carries session totals reported by the source.

| Field | Req | Meaning |
|---|---|---|
| `title` | O | Replacement title |
| `endedAt` | O | Recorded session end time |
| `repos` | O | Additional repositories, with the shape used in `session` |
| `usage` | O | Source session total using the [usage shape](#usage-and-cost), with optional boolean `includesSubagents` |
| `cost` | O | Source session total using the [cost shape](#usage-and-cost) |
| `agentSettings` | O | Object with the agent settings described below |
| `tools` | O | Tools the source recorded as offered from this position, using the shape below |
| `missing` | O | Array of strings adding to the session's [known losses](missing-data.md#known-losses) |

**ASR-020** A `session_info` MUST contain at least one field from this table and use these field shapes. Readers MUST replace supplied values without erasing omitted fields, except `repos`, which adds repositories, and `missing`, which adds losses. They MUST apply `agentSettings` and its `modelSettings` updates one field at a time, treating a field set to `null` as clearing that fact to unknown, and replacing a supplied `externalSandbox` object as a whole. A producer that supplies `externalSandbox` MUST include every fact in it that it still knows. Producers MUST preserve `mode`, `approval` and `sandbox` verbatim from the source, record `modelSettings` only from configured values stated by the source, and emit a new `session_info` when the source records a change.

Each supplied `usage` or `cost` object replaces the earlier total of that kind. Omitted fields do not erase earlier facts. `includesSubagents: true` says the usage total includes children, `false` says it excludes them, and absence leaves that scope unknown. Do not add child usage to a total that includes children or has unknown scope. The cost total has no separate scope flag.

`agentSettings` records the agent's operating mode, policies and configured model settings. All fields are optional and accept `null` to clear their value. Fields within `modelSettings` also accept `null`. Clearing `modelSettings` itself clears all its configured values.

| Field | Req | Meaning |
|---|---|---|
| `mode` | O | String with the agent's working mode, such as plan, ask or a selected agent |
| `approval` | O | Any JSON value with a permission or approval mode or policy, verbatim |
| `sandbox` | O | Any JSON value with the sandbox policy, verbatim |
| `asks` | O | String, `always`, `sometimes` or `never`, describing whether the policy can require a person to approve file changes or commands |
| `externalSandbox` | O | Object describing a recorded outer boundary, as described below |
| `modelSettings` | O | Configured model settings, using the same fields as [inference settings](#inference) |

A record supplying only `agentSettings.mode` keeps the recorded `approval` and `sandbox` values. An empty `agentSettings` or `modelSettings` object changes nothing. The native fields have no shared policy vocabulary. Readers can display them and compare them within one agent.

The settings in effect for a record come from the `session_info` updates before it in file order. A mode change belongs at that point in the stream. Omitted fields retain their last supplied values, subject to the `asks` rule below. Within a supplied `externalSandbox`, omitted facts become unknown. Supplying an empty `externalSandbox` clears its facts.

`modelSettings` holds configured values. `inference.settings` holds values the source recorded for a call or its containing turn. Readers do not treat the configured values as what a call sent or fill absent call settings from them.

`asks` describes whether a person is asked before actions that change files or run commands. `always` means every such action requires a person, `sometimes` means some can require a person, and `never` means no person is asked. Rules can still refuse actions. It describes what the recorded policy can require, not how many prompts happened. The native `approval` and `sandbox` values remain the primary evidence.

The optional `externalSandbox` object records a boundary outside the agent process, such as a container, VM or remote host the agent and its work ran in. A sandbox used only by some tools does not establish that boundary.

| Field | Req | Meaning |
|---|---|---|
| `kind` | O | `container`, `vm`, `remote` |
| `source` | O | `setting` for a declaration, `environment` for a launcher marker, `detected` for agent detection |
| `native` | O | The source's own value, any JSON |

**ASR-072** Producers MUST derive `asks` only from settings recorded for the session or observed in effect by a live writer, and MUST omit it when they cannot derive it. They MUST NOT fill it from configuration read at conversion time, documented defaults or tool outcomes. When `mode`, `approval` or `sandbox` changes without a supplied `asks`, readers MUST treat the earlier `asks` as unknown. Producers MUST supply `asks` again when they can still establish it. Producers MUST record `externalSandbox` only when the source states an outer boundary, at the position where it applies.

A latest-value snapshot does not establish an earlier boundary.

Each entry in `tools` describes a tool offered to the model.

| Field | Req | Meaning |
|---|---|---|
| `name` | R | String with the tool's name |
| `description` | O | String with its recorded description |
| `inputSchema` | O | Its recorded input schema as JSON |
| `source` | O | String naming its source, such as an MCP server |

**ASR-074** Producers MUST record `tools` only from definitions the source recorded as offered or a recorder observed as offered. A producer that knows the list is partial MUST list `tools` in `missing`. Readers MUST replace the tool list as a whole when supplied and apply it from that position in file order.

An empty `tools` array records an empty list. An omitted array keeps the last supplied list, or leaves it unknown if none was recorded. A partial list does not establish that an unlisted tool was unavailable. Tool definitions can contain private instructions, so the [safety rules](missing-data.md#safety) apply.

An ended session can resume under the same identity. End of file says nothing about whether the session ended.

```jsonl
{"type":"session_info","id":"info-1","title":"Handle empty input","endedAt":"2026-10-26T14:03:10Z","usage":{"inputTokens":1200,"outputTokens":180,"includesSubagents":false},"cost":{"amount":0.004,"currency":"USD","source":"provider_reported"}}
```

## `message`

A message keeps the content stored by the source. Its role does not identify its author.

Record the system prompt and developer instructions as messages with `role: system` or `developer` and `origin: instructions`, at their position in the stream.

| Field | Req | Meaning |
|---|---|---|
| `role` | R | `user`, `assistant`, `system`, `developer` |
| `content` | R | Ordered [content parts](format.md#content-parts), possibly `[]` |
| `author` | O | `human`, `model`, `harness`, `hook`, `tool`, `agent` |
| `person` | O | Person who wrote or sent the message, using the shared [identity shape](#session) |
| `origin` | O | `prompt`, `queued`, `command`, `injected`, `instructions`, `memory`, `compaction`, `subagent_report`, `notice`, `scheduled`, `external` |
| `phase` | O | Assistant phase, `commentary` or `final` |
| `status` | O | `complete`, `interrupted`, `error` |
| `from` | O | Session reference of another session that sent the message |

**ASR-021** A `message` MUST have `role` and `content` and MUST use the field shapes above.

**ASR-022** Producers MUST use `author: "human"` only when the source distinguishes a person's input. They MUST record a compaction summary with `origin: "compaction"`, and readers MUST NOT treat it as a person's prompt or derive edits or commits from its text. A `gap` MUST follow when compaction destroyed earlier history.

A harness can inject a message with `role: "user"`. That role alone does not establish human authorship. Part-level `author` and `origin` override the message values for mixed content.

`person` identifies the person when the source records one per message, such as in a group chat. It does not replace `author`. `author: "human"` says a person wrote the message, while `person` says which one.

`origin` says how a message arrived, while `author` says who wrote it. `scheduled` means a schedule or timer started the message. `external` means an outside event delivered it, such as a webhook, chat channel message or issue event. A scheduled prompt written by a person can have `author: "human"` and `origin: "scheduled"` when the source records both. If the source records the trigger on the session, put it on the run's first message. Keep schedule, delivery and channel IDs in `_meta` under the agent's reverse-DNS key.

```jsonl
{"type":"message","id":"prompt-1","turnId":"turn-1","role":"user","author":"human","origin":"prompt","content":[{"type":"text","text":"Return an empty list for empty input."}]}
```

## `tool_call`

A call records a tool request. The call's `id` identifies this record, while `callId` links the request to its result and effects.

| Field | Req | Meaning |
|---|---|---|
| `callId` | R | Native call ID, or a deterministically derived ID |
| `name` | O | Tool name exactly as requested |
| `kind` | O | ACP ToolKind, listed below |
| `input` | O | Arguments the tool received, as JSON |
| `inputText` | O | Arguments as a string when not JSON |
| `requestedBy` | O | `model`, `user`, `harness`, `code` |
| `parentCallId` | O | Enclosing call ID when the source records one |
| `locations` | O | Array of objects with required `path` and optional integer `line` of at least 1 |
| `subagent` | O | Object with optional `session`, `role` and `description` when this call starts a subagent |

**ASR-023** A `tool_call` MUST have `callId` and use these field shapes. It MUST NOT contain both `input` and `inputText`.

**ASR-024** Producers MUST keep recorded call IDs and tool names. They MUST take `kind` from the source or a fixed name-to-kind map in converter notes, and MUST NOT infer `requestedBy: "model"` from its absence.

The known kinds are `read`, `edit`, `delete`, `move`, `search`, `execute`, `think`, `fetch`, `switch_mode` and `other`. `requestedBy: "code"` means a program the model wrote requested the call. `locations` identifies files read or targeted by the call and supports searches for sessions that read a file. The `line` follows ACP's 1-based line numbering when recorded. A missing `name` produces a validator warning.

`input` holds the arguments the tool received. When a hook or client rewrote them and the model's original request is recorded, keep that original under the agent's reverse-DNS key in `_meta`. A live writer can supply arguments learned at completion on the result.

```jsonl
{"type":"tool_call","id":"call-read","callId":"read-1","name":"read_file","kind":"read","input":{"path":"/work/app/src/parser.py"},"requestedBy":"model","locations":[{"path":"/work/app/src/parser.py","line":1}]}
```

## `tool_result`

A result records the source's outcome and output.

| Field | Req | Meaning |
|---|---|---|
| `callId` | O | Call being answered, absent when the source cannot link it |
| `status` | R | `completed`, `failed`, `denied`, `cancelled`, `interrupted`, `unknown` |
| `content` | O | Result content as ordered parts |
| `input` | O | Effective JSON arguments learned at completion that differ from the call's recorded input |
| `inputText` | O | Effective string arguments learned at completion that differ from the call's recorded input |
| `error` | O | Object with optional string `message` and `code` of any JSON type |
| `exec` | O | Shell details, described below |
| `durationMs` | O | Non-negative number of milliseconds |
| `subagent` | O | Object with required `session` reference when the child becomes known at completion |

`exec` can contain `command` as a string or string array, `cwd` as an absolute path, integer `exitCode`, and strings `signal`, `stdout`, `stderr` and combined `output`. These fields are optional. Separate output streams and combined output retain the source's representation.

**ASR-025** A `tool_result` MUST have the source's `status` and use these field shapes. Producers MUST NOT derive status from exit codes or output text unless the source does, MUST record an exit code only when supplied by the source, and MUST use the model-facing result for `content` when the source stores both model-facing and display forms.

**ASR-076** A live writer MAY supply `tool_result.input` or `inputText` when it learns the arguments only at completion and they differ from the call's recorded input. A result MUST NOT contain both fields. Readers MUST use the result's supplied arguments as the effective input for its uniquely paired call.

An absent call input also differs from newly learned arguments. The result preserves those arguments without rewriting the call. An empty string or JSON `null` is a supplied argument value.

**ASR-026** A file MUST contain at most one `tool_result` per `callId`. Readers MUST pair a result with a call only when exactly one `tool_call` in the file has that `callId`. Otherwise they MUST show the result as unpaired. A call without a result MUST have an unknown outcome.

Fold native result updates into one completed result. Results without a `callId` remain unpaired. Duplicate call IDs make pairing ambiguous even when the calls have distinct `id` values. Readers do not choose a call by proximity or text similarity.

```jsonl
{"type":"tool_result","id":"result-read","callId":"read-1","status":"completed","content":[{"type":"text","text":"def parse(text):\n    return text.split(',')\n"}]}
```

## `approval`

An approval records one decision at its source position, or immediately before its result under the [folding and snapshot rule](format.md#file-format-and-order). Its envelope supplies its own ID and optional time. One call can have several decisions, such as a command approval followed by a sandbox escape. Write each as a separate record, even if the call never finishes.

| Field | Req | Meaning |
|---|---|---|
| `callId` | O | Call this decision concerns |
| `decision` | R | `approved`, `denied`, `cancelled` |
| `by` | O | `user`, `policy`, `mode`, `hook`, `classifier`, `fallback` |
| `scope` | O | `once`, `session`, `always`, by the grant's actual lifetime |
| `subject` | O | Verbatim string naming a request narrower than the whole call, or the subject of a decision with no call |
| `person` | O | Person who answered, using the shared [identity shape](#session) |
| `native` | O | The source's own value, any JSON |

`cancelled` means the request ended without an answer, for example because the turn was cancelled or the request expired. A `cancelled` decision has no `scope` and no `person`, because nobody answered. A supplied `person` means that person answered this request, so `by` is `user` when both are present.

| `by` | Meaning |
|---|---|
| `user` | A person answered this request |
| `policy` | Settings, rules or a remembered grant allowed or refused it |
| `mode` | The agent's mode allowed or refused it without checking rules |
| `hook` | A hook program decided |
| `classifier` | An automatic reviewer decided |
| `fallback` | No person was available, so the agent applied its default |

`once` covers this request. `session` lasts until the session ends, including thread or conversation grants. `always` is kept beyond the session. Some agents label session grants "always", so a converter note establishes the actual lifetime. Without a recorded decision, the answer stays unknown. Approval does not establish execution or success.

**ASR-073** An `approval` MUST have `decision` and use these field shapes. Producers MUST record only approval decisions the source states, in source order, and MUST NOT infer a decision from a tool's outcome, the agent's settings or the session's mode. They MUST record a reused grant as `by: "policy"` rather than `user`, and MUST set any supplied `scope` from the grant's actual lifetime.

Readers join approvals by `callId` only when exactly one call has that ID. Several decisions can share it. A decision with no tool call has no `callId`. Its `subject` names what was decided, such as a network host or an MCP server, when the source records it. Without a recorded subject, the decision keeps its position and what it concerned stays unknown. For a linked decision, an absent `subject` means the whole call. A narrower request, such as a sandbox escape, keeps its recorded subject.

```jsonl
{"type":"approval","id":"approval-test","callId":"exec-1","decision":"approved","by":"user","scope":"once","native":{"choice":"allow_once"}}
{"type":"tool_result","id":"result-test","callId":"exec-1","status":"completed","exec":{"command":"pytest","exitCode":0}}
{"type":"approval","id":"approval-host","decision":"approved","subject":"packages.example.com","by":"user","scope":"session"}
```

## `file_change`

This record describes one file. A call that changes several files produces one record per file with the same `callId`.

| Field | Req | Meaning |
|---|---|---|
| `path` | R | File path using the [path rules](format.md#paths) |
| `op` | R | `add`, `modify`, `delete`, `move`, `copy`, `unknown` |
| `oldPath` | C | Source path, required for `move` and `copy` |
| `status` | R | `applied`, `proposed`, `failed`, `unknown` |
| `callId` | O | Tool call that made the change |
| `actor` | O | `human`, `harness`, `hook`, `external`, when no tool call made it |
| `before`, `after` | O | Objects with optional `text`, `objectId` and `objectIdType` |
| `patch` | O | Recorded unified diff text for this file |
| `edits` | O | Array of replacements, each with required `oldText` and `newText` strings |
| `baseCommit` | O | Full HEAD commit ID at the time of the edit |

**ASR-027** A `file_change` MUST describe one file, have `path`, `op` and `status`, and use these field shapes. `move` and `copy` MUST have `oldPath`. A record MUST NOT contain both `patch` and `edits`, or both `callId` and `actor`.

**ASR-028** Producers MUST use `status: "applied"` only for a change carried out, and MUST use `actor` only when no tool call made the change. `actor: "external"` MUST mean the source observed a change without knowing who made it.

**ASR-029** `before.text` and `after.text` MUST represent full file contents. Object IDs MUST come from content observed at the edit, never from hashing the file later. A producer MUST preserve a recorded patch and MUST NOT synthesize a diff.

`edits` preserves replacement strings without inventing positions. An empty `oldText` or `newText` is a recorded value. A requested replacement alone does not establish that it was applied.

**ASR-030** File object IDs MUST be lowercase hexadecimal with the length required by `objectIdType`: 40 digits for `git-blob-sha1`, 64 for `git-blob-sha256` or `sha256`. An absent `objectIdType` MUST mean `git-blob-sha1`.

Git blob IDs use Git's blob hashing, including its object header. `sha256` is the hash of the file contents. Readers use the declared algorithm when comparing with a repository blob.

Full text or an object ID supplies an exact file state, a patch supplies hunks, and `edits` supplies snippets. A record with none of those still says the file was touched. [Edited by](code.md#edited-by) defines how each form supports line attribution.

```jsonl
{"type":"file_change","id":"change-1","path":"/work/app/src/parser.py","op":"modify","status":"applied","callId":"edit-1","edits":[{"oldText":"    return text.split(',')\n","newText":"    return text.split(',') if text else []\n"}]}
```

## `vcs`

This record describes a version-control action the session performed or a pull request it referred to or looked up.

| Field | Req | Meaning |
|---|---|---|
| `action` | R | Action listed below |
| `status` | R | `completed`, `failed`, `unknown` |
| `evidence` | R | `observed`, `parsed_output`, `reported` |
| `callId` | O | Tool call that ran the action |
| `actor` | O | `human`, `harness`, `hook`, `external`, when no tool call did it |
| `repo` | O | Absolute repository path |
| `commit` | O | Full resulting commit ID |
| `commitPrefix` | O | Abbreviated ID as printed, 7 to 39 lowercase hexadecimal digits |
| `subject` | O | Commit subject as printed or recorded |
| `parents` | O | Array of full parent commit IDs |
| `parentCount` | O | Non-negative integer parent count when known |
| `headBefore`, `headAfter` | O | Full HEAD commit IDs before and after the action |
| `rewrites` | O | Array of exact commit pairs, each with required `from` and `to` |
| `branch`, `remote` | O | Recorded labels |
| `pr` | O | Pull request object, described below |

The known actions are `commit`, `amend`, `merge`, `rebase`, `cherry_pick`, `revert`, `reset`, `checkout`, `branch_create`, `push`, `pr_open`, `pr_merge` and `pr_link`.

`evidence: "observed"` means structured data from the harness, a tool or a repository hook. `parsed_output` means facts parsed from command output. `reported` means a stored association without a record of the action itself. These values describe how the fact is known.

`pr` has optional strings `url`, `repository` and `state`, an integer `number` of at least 1, full commit IDs `headCommit` and `mergeCommit`, and an array of full IDs `commits`. It identifies the pull request by `url`, or by both `repository` and `number`. The known states are `open`, `closed` and `merged`. `commits` lists observed member commits without claiming that the list is complete.

**ASR-031** A `vcs` MUST have `action`, `status` and `evidence` and use these field shapes. Full commit IDs throughout ASR MUST be 40 or 64 lowercase hexadecimal digits. A record MUST NOT contain both `commit` and `commitPrefix`, or both `callId` and `actor`. A `pr` object MUST have `url` or both `repository` and `number`.

**ASR-032** When both `parents` and `parentCount` are present, the count MUST equal the array length. Every `rewrites` pair MUST have different full commit IDs for `from` and `to`. All full commit IDs within one `vcs` record or `vcs` annotation payload MUST have the same length.

**ASR-033** Producers MUST record version-control actions and pull request references only from the source, distinguish their evidence as defined above, and MUST NOT turn a commit mention or `git log` entry into an action by the session.

When `repo` is absent and the session lists exactly one repository, that repository is implied. With several repositories, an absent `repo` leaves the association unknown. Branches and remotes are labels, not identities.

A `pr_link` can record a merge commit learned through a forge query during the session. It establishes an association with the pull request, not that this session created the commit. Facts learned afterward belong in [annotations](annotations.md).

```jsonl
{"type":"vcs","id":"commit-1","action":"commit","status":"completed","evidence":"parsed_output","callId":"commit-call","repo":"/work/app","commitPrefix":"8e2f4a6","subject":"Handle empty input"}
```

## `inference`

An inference is one model call. Its record `id` is the target of an `inferenceId` on messages or tool calls it produced.

| Field | Req | Meaning |
|---|---|---|
| `model` | O | Object with optional `provider`, `id` and `requested`, with at least `id` or `requested` when supplied |
| `settings` | O | Object with the model settings in effect for this call, as described below |
| `usage` | O | Usage for this call only |
| `cost` | O | Cost for this call only |
| `stopReason` | O | Provider value, verbatim |
| `durationMs` | O | Non-negative number of milliseconds |
| `error` | O | Object with optional string `message` and `code` of any JSON type |

**ASR-034** Producers MUST emit `inference` only for a model call identified by the source, use a unique provider request or response ID when available, and MUST NOT synthesize calls from message boundaries.

When a derived ID is used for the inference, keep the provider response ID under the agent's reverse-DNS key in `_meta`. That ID can join the call to vendor usage and audit exports.

A source without model-call boundaries omits these records and lists `usage` in `missing`, or supplies recorded totals in `session_info`. It does not divide a session total among guessed calls.

**ASR-035** An `inference` MUST use these field shapes. When the source identifies a model call but not its model, producers MUST omit `model` and list `model` in `missing`. A supplied `model` MUST have at least one of `id` and `requested`. `id` MUST identify the model reported as having served the call, and `requested` MUST identify the requested alias or configured model. Producers MUST NOT copy either value into the other. Producers MUST record only settings stated by the source for this call or its containing turn, apply recorded turn settings to each inference in that turn, and MUST NOT fill in unstated defaults.

`settings` has these optional fields. String values are verbatim from the source.

| Field | Req | Meaning |
|---|---|---|
| `reasoningEffort` | O | String with the reasoning effort, for example `"high"` |
| `maxOutputTokens` | O | Non-negative integer output token limit |
| `temperature` | O | Number with the recorded sampling temperature |
| `serviceTier` | O | String with the recorded service tier |

Other settings go in the inference record's `_meta` under the agent's reverse-DNS key. An empty `settings` object states no settings. Missing settings remain unknown even when the agent has a documented default.

### Usage and cost

All fields in the usage object are optional non-negative integers.

Usage the source reports for part of a turn without call boundaries stays under the agent's key in `_meta`.

| Field | Meaning |
|---|---|
| `inputTokens` | Total input tokens, including cache reads and writes |
| `cacheReadTokens` | Input tokens read from cache |
| `cacheWriteTokens` | Input tokens written to cache |
| `outputTokens` | Total output tokens, including reasoning |
| `reasoningTokens` | Output tokens used for reasoning |

**ASR-036** Producers MUST normalize usage to these inclusive totals, preserve reported zero values, and MUST NOT substitute zero for an unknown count.

Follow the source's accounting rules in its [converter notes](../agents/index.md). A mapping can define a total as the base count plus each supplied optional component. Apply that formula even when an optional component is absent, while leaving that component's field absent. A count lost through truncation or corruption remains unknown. Do not add cache or reasoning again when the source total includes it. This matches [OpenTelemetry GenAI usage conventions](../guides/otel.md).

Cost has required numeric `amount` and ISO 4217 `currency`, with optional `source`. Its known source values are `provider_reported`, `harness_estimated` and `converter_estimated`.

**ASR-037** A cost object MUST have `amount` and `currency` and use the cost shape above. Absent cost MUST remain unknown, not zero.

**ASR-038** Readers MUST sum per-call figures using the [copy credit rule](sessions.md#copies-and-credit) and MUST NOT add `session_info` totals to those figures or sum successive session totals.

Cache and reasoning counts are parts of the inclusive totals. Adding them to those totals would count them twice. Report cost by model and currency without treating unknown calls as free.

```jsonl
{"type":"inference","id":"model-call-1","model":{"provider":"example","id":"example-model-1","requested":"default"},"usage":{"inputTokens":1200,"cacheReadTokens":200,"outputTokens":180,"reasoningTokens":40},"cost":{"amount":0.004,"currency":"USD","source":"provider_reported"},"stopReason":"tool_use"}
```

## `gap`

A gap marks the place where history is missing.

| Field | Req | Meaning |
|---|---|---|
| `reason` | R | `not_retained`, `deleted`, `unparseable`, `redacted`, `not_recorded`, `unknown` |
| `count` | O | Non-negative integer number of missing records or source lines, when known |
| `detail` | O | Plain text explanation |

**ASR-039** A `gap` MUST have `reason` and use these field shapes. A converter encountering corrupt source data MUST emit a gap instead of silently skipping the data.

A gap does not prove that an event did not happen. The absence of a gap does not prove that all history was captured. See [Missing data](missing-data.md).

```jsonl
{"type":"gap","id":"gap-1","reason":"unparseable","count":1,"detail":"One native log line could not be read."}
```
