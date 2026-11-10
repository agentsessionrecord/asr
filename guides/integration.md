---
title: "Integration"
description: "Commit trailers, an export command convention and session discovery."
---

## The Agent-Session trailer

A commit message can name each Agent Session Record (ASR) session that contributed to it with an `Agent-Session` trailer:

```text
Handle empty limits

Agent-Session: com.example.coder:parser-42#commit
Agent-Session-Url: https://sessions.example.com/parser-42
```

The value is a [session reference](../spec/format.md#identity-and-session-references), optionally with a record fragment, and nothing else. Trailers are printable ASCII, so percent-encode non-ASCII UTF-8 bytes as well as the reference grammar's reserved characters, using uppercase hexadecimal. Write one trailer per session. An optional `Agent-Session-Url` goes right after its session's trailer. The URL can change, expire or require access, so it locates the session but doesn't identify it.

A trailer tells a reader which session to check, not who committed or wrote anything. Apply the [committed-by checks](../spec/code.md#committed-by) and inspect the surviving edits before claiming authorship.

Add trailers when the repository's user has turned them on, and don't rewrite existing commits to add them. Squash merges can drop trailers, so readers also use the recorded pull request and commit associations.

## Export command convention

An agent can offer an export command with this shape:

```text
<agent> sessions export --format agent-session
    [--session <sessionId>]...
    [--since <RFC 3339 timestamp>]
    [--output <directory>]
```

With exactly one `--session` and no `--output`, the command writes that session's JSONL stream to standard output. With `--output`, it writes one `.jsonl` file per selected session. `--since` selects sessions changed since the given time. If a request would send several sessions to standard output, reject it rather than mix their headers.

Choose filenames safely and never treat a session ID as a path. Each file's header carries its identity, so the directory needs no manifest. Write diagnostics to standard error, exit with zero on success and nonzero on failure, and report unavailable source files instead of writing them out as empty sessions.

A converter can re-export a whole file as its source changes, while a live writer appends complete lines. Keep record IDs the same across exports wherever the native identity is unchanged. The [tool-builder guide](../site/pages/get-started/tool-builders.mdx#updates-and-retention) covers how readers handle both.

## Discovery file

An agent can describe its sessions in `$XDG_CONFIG_HOME/agent-sessions/sources/<agent>.json`, which defaults to `~/.config/agent-sessions/sources/<agent>.json`. On Windows the file is `%APPDATA%\agent-sessions\sources\<agent>.json`. The [discovery schema](https://agentsessionrecord.org/schema/v0/discovery.schema.json) defines these fields:

| Field | Meaning |
|---|---|
| `agent` | Required agent short name or reverse-DNS name. |
| `namespace` | Installation namespace, only when native session IDs repeat. Persist a generated namespace so it stays stable. |
| `exportCommand` | Executable and arguments as an array of strings. |
| `nativePaths` | Patterns for native session storage, with `~` denoting the user's home directory. |
| `formatVersions` | ASR versions the exporter can write. |
| `supportsDeletionHook` | Whether the agent can notify consumers before deleting native sessions. |
| `_meta` | Vendor data under reverse-DNS keys. |

A discovery file advertises a source but doesn't authorize running its command. Let the user enable the source and check which executable it names, then run the argument array without a shell. Never run a command found inside a session stream.

Native storage can move between releases, so keep `nativePaths` and `formatVersions` current. A converter can also read a source the user picks without any discovery file.

`supportsDeletionHook: true` says the agent can send a notification before it deletes native sessions. It doesn't define a hook transport, register a consumer or guarantee delivery. The [tool-builder guide](../site/pages/get-started/tool-builders.mdx#updates-and-retention) covers what a reader does when a source is deleted.

## Later facts and access

Facts learned after a session, such as a merge recorded by a forge sync or a test service's result, go in a separate `.annotations.jsonl` file and join the session by its reference. See [Annotations](../spec/annotations.md).

Keep transcript content out of commit messages and Git notes. Even a bare reference reveals that a session exists, so publish links only when the repository has chosen to, and put access control on any service that resolves session URLs. A stream that validates can still be unsafe to publish.

The [Git AI guide](git-ai.md) covers line attribution notes, and the [ACP guide](acp.md) covers recording a live connection.
