# OpenCode family recorder

Live-test status: **partial**. The current recorder passes offline regression
checks. A live run of this revision is pending.

This passive TypeScript plugin writes Agent Session Record 0.1 files from
OpenCode, Kilo Code and MiMoCode callbacks. Each native session gets one local
file. Existing complete files are appended under the same identity on resume.

## Install

Build from this repository with Node 22.13 or later and pnpm:

```sh
pnpm install --frozen-lockfile
pnpm --filter @agent-session/types build
pnpm --filter @agent-session/writer build
pnpm --dir plugins/opencode build
```

Keep the checkout and its dependencies available while the plugin is installed.
Add the entry file to the agent's normal plugin list. Merge the list with any
existing plugins. Use an absolute file URL.

| Agent | Configuration | Entry file |
| --- | --- | --- |
| OpenCode 1.19.5 | `opencode.json`, `plugin` list | `dist/index.js` |
| Kilo Code 7.8.18 | `kilo.json`, `plugin` list | `dist/kilo.js` |
| Older Kilo source | `opencode.json`, `plugin` list | `dist/kilo.js` |
| MiMoCode 0.1.16 | `.mimocode/mimocode.json`, `plugin` list | `dist/mimocode.js` |

For example, an OpenCode project configuration can contain:

```json native
{
  "plugin": ["file:///absolute/asr/plugins/opencode/dist/index.js"]
}
```

Set an output directory in the agent's environment, then launch it normally:

```sh
export ASR_OUTPUT_DIR=/absolute/private/agent-records
opencode
```

Without `ASR_OUTPUT_DIR`, the recorder writes nothing. The directory is created
with mode 0700 and new files with mode 0600. Existing directories must be owned by the current user and have mode 0700. Filenames contain the agent name and a SHA-256 digest of
the native session ID. Native IDs remain verbatim in the header.

The newer OpenCode source has a V2 plugin API. Its entry is `dist/v2.js`.
It uses domain hook registration and an event subscription. This adapter has
synthetic contract tests. It has not been live-tested against a V2 binary.
See [the source notes](SOURCES.md) for the API boundary and configuration.

## Content

The default `ASR_CONTENT=metadata` omits arguments, output and text. It retains
session identity, lifecycle observations, tool names, call IDs, outcomes,
permission replies and observed modes. Omissions are declared in `missing`.
Affected records have `truncated: true`.

Set `ASR_CONTENT=full` to keep available arguments and text. Known credential
fields, common token formats and values from secret-bearing environment
variables are excluded in both modes. These filters do not establish that a
record is safe to share. Review recorded content before sharing it.

No headers, credential store, model request bodies or global history are read.
The recorder makes no network requests and changes no tool arguments, results,
permission decisions or session settings.

## Recorded evidence

The producer method is `recorder`. Every record uses callback receipt time.
An observed `session.created` can set `startedAt`. Idle, turn completion,
deletion and process exit do not establish session end.

`tool.execute.before` writes a call without effective input. In full mode its
observed request is kept under `org.agentsessionrecord.hooks` in `_meta`.
The after hook supplies executed arguments. The terminal bus item supplies
the final result after other plugins have finished editing output.
The recorder writes one result at that completion point. Late effective
arguments go in `tool_result.input`. Executed after-hook arguments take
precedence over a request retained in the terminal part.

The fixed tool-kind map is `bash` and `shell` to `execute`, `read` to `read`,
`edit`, `write` and `apply_patch` to `edit`, `glob`, `grep` and `websearch` to
`search`, `webfetch` to `fetch`, and `task` to `other`. Unknown names have no
kind. A nonzero exit code does not change the native outcome.

Permission requests and provisional `permission.ask` or V2 `evaluate` status
are observations in the declared `org.agentsessionrecord.hooks/v1`
extension. They do not become approvals. An explicit `permission.replied`
becomes an approval with the native reply. `once` has scope `once`.
The event does not distinguish a direct reply from a timeout or cascaded
decision, so the decider stays unknown. `always` has no normalized scope
because the forks use different grant lifetimes. Missing subjects are omitted.
Linked decisions omit subjects that merely name the tool permission.

The extension also retains lifecycle observations and completed text parts
whose role cannot be established from that callback alone. Unknown extension
and type warnings from the validator are expected. Core-only readers can
still read calls, results, approvals and settings.

## Limits

Hooks do not report every policy allow or denial, every hook's final verdict,
all mode changes, model calls, usage, costs, full instructions or offered tools.
These losses are declared in the header. File edits and commits are not
normalized. Text parts do not establish human or model authorship. A native
parent ID is retained as metadata without guessing whether it means a fork
or a subagent. A task result can link an explicitly named child session.
MiMoCode can route tool programs through an `exec` wrapper. Its nested tool
calls do not necessarily have separate callbacks. The wrapper's effective
program and result are kept in full mode, and `nested_tool_calls` is declared
missing. The recorder does not parse a program to invent nested calls.

Callbacks copy a bounded snapshot and return without waiting for storage.
Queued writes use the writer library on the next event-loop turn. Storage
errors fail open and add fixed-code diagnostics to a private local file.
An intact stream receives a sealing gap and a loss update before capture stops. An exit handler flushes queued observations.
Abrupt termination can lose callbacks. The header declares this limit.

There are at most 256 queued snapshots, 64 attached or disabled sessions,
2,048 pending tool or permission entries per session and 4,096 text identities.
A snapshot has a 128 KiB text budget, a 64 KiB per-string limit and a 4,096-node
limit. A stream stops at 100,000 records. Queue losses produce a gap at the next
observation when storage remains available.

A process lock protects each stream. A dead owner's lock can be reclaimed.
A second live writer waits at most 100 ms, then skips the session. Its loss
marker is consumed by the active writer before the next callback. Resume requires an intact regular file
of at most 16 MiB from this producer. A partial tail, invalid record, symbolic
link or foreign stream is left untouched. A resumed stream gets a gap because
events between attachments are unknown. Capture has no durability guarantee
after a filesystem error or forced process termination.

## Uninstall

Remove the entry from the agent's plugin list and restart the agent. Unset
`ASR_OUTPUT_DIR` and `ASR_CONTENT` if they were set for this recorder. Keep or
delete the output directory according to your retention policy. Uninstalling
does not delete recordings.

## Tests

```sh
bash plugins/opencode/check.sh
```

The tests use synthetic callbacks for all three agents and V2. Every generated
stream is checked with the repository validator. The committed callback trace
is in `test/fixtures/legacy.json`. The replay script creates reproducible ASR:

```sh
node plugins/opencode/scripts/replay.mjs /absolute/new/synthetic-output
```

OpenCode 1.19.5, Kilo Code 7.8.18 and MiMoCode 0.1.16 were live-tested with an
isolated configuration and a local OpenAI-compatible model endpoint. All three
ran a synthetic command without an agent account. See `evidence/live-summary.json`
for counts and validation codes.

To repeat the live check with a separately installed CLI, set
`ASR_OPENAI_BASE_URL`, `ASR_OPENAI_MODEL` and `ASR_PROVIDER_KEY_FILE`.
Use an explicit loopback URL for the OpenAI-compatible endpoint and a private
credential file. Then run:

```sh
node plugins/opencode/scripts/live-test.mjs opencode /absolute/prefix/bin/opencode summary.json
```

Use `kilo` or `mimocode` as the first argument for those agents. OpenCode and
Kilo Code check a rewrite and a refusal. MiMoCode checks a wrapper command.
The runner
creates isolated configuration, disables optional integrations, validates its
streams and removes its temporary files. Its output contains counts and codes.


Credential patterns and session reference encoding come from the writer package.
Ordinary token counts remain available. Secret-valued native identities produce
loss markers instead of changed join keys. Producers use `asr-hooks-<agent>` and
hook records use `org.agentsessionrecord.hooks/hook`. Shared loss names include
`redacted_content`, `content`, `session_lifecycle` and `dropped_callbacks`.
