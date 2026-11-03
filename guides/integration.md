---
title: "Integration"
description: "Commit trailers, an export command convention and session discovery."
---

This guide describes small interfaces for finding and exporting ASR sessions. It adds no requirements. An agent can produce valid ASR without implementing them.

## The Agent-Session trailer

A commit message can carry one `Agent-Session` trailer per contributing session:

```text
Handle empty limits

Agent-Session: com.example.coder:parser-42#commit
Agent-Session-Url: https://sessions.example.com/parser-42
```

The trailer value is a [session reference](../spec/format.md), optionally ending in a record fragment. Keep it separate from the URL or commentary. For printable ASCII trailers, percent-encode non-ASCII UTF-8 bytes as well as the reference grammar's reserved characters. Use uppercase hexadecimal escapes.

Several sessions can contribute to one commit. Write each session once. An optional `Agent-Session-Url` immediately follows its session trailer. It is a locator and can change, expire or require access. It is not the session's identity.

The trailer helps a reader find a candidate session. Apply the [committed-by checks](../spec/code.md#committed-by) and inspect surviving edits before claiming authorship. A trailer alone establishes neither.

Add trailers when making a commit if the repository's user has enabled them. Do not rewrite existing commits merely to insert links. Squash merges may omit trailers, so readers also use recorded pull request and commit associations.

## Export command convention

An agent can offer a command with this shape:

```text
<agent> sessions export --format agent-session
    [--session <sessionId>]...
    [--since <RFC 3339 timestamp>]
    [--output <directory>]
```

With exactly one `--session` and no output directory, write that session's JSONL stream to standard output. With `--output`, write one `.jsonl` file per selected session. `--since` selects sessions changed since the supplied time. Reject ambiguous multi-session output to standard output rather than mixing session headers.

Choose filenames safely without interpreting session IDs as paths. Identity comes from each file's header. This convention defines a directory of files and does not require a manifest.

Write diagnostics to standard error. Exit with zero on success and nonzero on failure. Report unavailable source files without turning missing facts into empty successful sessions.

A converter can re-export a whole file as its source changes. Keep record IDs deterministic across exports where the native identity is unchanged. A live writer appends complete lines. Readers should distinguish an appended file from a replacement export when updating an index.

An agent's own export uses `producer.method: native`. A separate tool reading logs uses `converter`. Both identify the source format they read when applicable and list known losses.

## Discovery file

An agent can describe its source at `$XDG_CONFIG_HOME/agent-sessions/sources/<agent>.json`. The default is `~/.config/agent-sessions/sources/<agent>.json`. On Windows, use `%APPDATA%\agent-sessions\sources\<agent>.json`.

The [discovery schema](https://agentsessionrecord.org/schema/v0/discovery.schema.json) describes these fields:

| Field | Meaning |
|---|---|
| `agent` | Required agent short name or reverse-DNS name. |
| `namespace` | Installation namespace, only when native session IDs repeat. Persist a generated namespace so it stays stable. |
| `exportCommand` | Executable and arguments as an array of strings. |
| `nativePaths` | Patterns for native session storage, with `~` denoting the user's home directory. |
| `formatVersions` | ASR versions the exporter can write. |
| `supportsDeletionHook` | Whether the agent can notify consumers before deleting native sessions. |
| `_meta` | Vendor data under reverse-DNS keys. |

A discovery file advertises a source. It does not authorize running its command. A tool should let the user enable the source, check which executable it names, and invoke the argument array without shell evaluation. Never execute a command found inside a session stream.

Native storage may move between releases. Keep source paths and supported versions current. A converter can also accept a user-selected source without a discovery file.

`supportsDeletionHook: true` advertises a notification before native sessions are deleted. It does not define a hook transport, register a consumer or guarantee delivery. On notification, update source availability and apply the store's retention policy to indexed text and retained exports. Without a hook, reconcile availability during refresh. Deletion of a native file does not itself delete a separately retained export. The [tool-builder guide](../site/pages/get-started/tool-builders.mdx#updates-and-retention) covers index updates and storage.

## Later facts and access

Write facts learned after a session to a separate file ending in `.annotations.jsonl`. A forge sync can record a merge, and a test service can record an outcome. Join those records through the session reference. See [Annotations](../spec/annotations.md).

Keep transcript content out of commit messages and Git notes. A reference can itself disclose that a session exists, so make publishing links a deliberate repository setting. Apply access control to any service that resolves session URLs. A valid stream is not necessarily safe to publish.

For line attribution notes, use the [Git AI guide](git-ai.md). For exporting a live connection, use the [ACP guide](acp.md).
