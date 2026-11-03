# Git notes and Git AI

Link a local Git commit to ASR sessions. Export verified edit matches as Git AI
authorship notes. No command pushes notes or changes commit history.

## Install and run

Use Node.js 22.13 or later and the repository's pnpm version. From the repository root:

```sh
pnpm install --frozen-lockfile
node --experimental-strip-types exporters/git-notes/cli.ts inspect config.json HEAD
node --experimental-strip-types exporters/git-notes/cli.ts write-links config.json HEAD
node --experimental-strip-types exporters/git-notes/cli.ts export-ai config.json HEAD > authorship.txt
node --experimental-strip-types exporters/git-notes/cli.ts write-ai config.json HEAD
node --experimental-strip-types exporters/git-notes/cli.ts read-ai config.json HEAD
```

Create an operator-owned config. Paths are relative to the current working directory.
The store holds ASR streams and optional `.annotations.jsonl` files. Symlinks are skipped.

```json native
{
  "repo": "/work/project",
  "store": "/work/sessions",
  "repositories": [{"source": "/recorded/project", "local": "/work/project"}],
  "sessionBaseUrl": "https://sessions.example.com/session"
}
```

Repository mappings explicitly bind recorded repository roots to the selected local
checkout. A matching current absolute root also works without a mapping. Remote names
and branch labels do not identify a repository. Configure mappings only for trusted stores.
Git must have an author identity configured before writing notes.

`write-links` stores references and optional configured locators under
`refs/notes/agent-sessions`. The JSON schema tag is `asr-links/1`. Each entry in
`sessions` has a `session` reference and optional `url`. Repeated writes merge by
reference and preserve unknown fields and numeric lexemes. Foreign note formats are
rejected. Locators from a stream or an existing note are never fetched.

`write-ai` stores an `authorship/3.0.0` note under `refs/notes/ai`. It refuses to replace
different existing content unless the operator sets `replaceGitAi` to `true` in the
config. This replaces the entire note. Save existing notes before enabling it.
Review `export-ai` output before choosing to write it.

## Evidence and limits

Commit credit and edited lines are separate fields in `inspect` output. Git blame
selects the introducing commit and path. Original completed VCS actions need observed
or parsed evidence. Unknown status can use only a unique completed result. Full IDs,
subjects and parent facts are checked. Prefixes also need unique resolution, the
required parent shape and reachability from a local branch or tag.

Edits need original applied file changes at a resolved repository path. The reader
uses before and after states, recorded replacement snippets or recorded patch additions.
Object IDs are checked against content with their declared hash algorithm. An after
state alone is used only for a recorded new file absent from the parent. Unchanged
context, ambiguous repeated text and file touches receive no line credit. Applied
moves and copies can carry earlier edit candidates. Recorded rewrite pairs are checked
against local commit objects. Annotations can connect history but never grant credit.

The latest surviving match within a session wins and retains earlier alternatives.
Matches across sessions have no established total order and remain competing. Human
edits are labeled as a person. External edits remain untracked. Missing calls, prompts
and models stay unresolved. Prompt text never enters notes.

Git AI's serializer and key functions are a TypeScript port of its reference
implementation. See [NOTICE](NOTICE) for the pinned source. Built-in tool mappings are
`claude-code` to `claude` and `codex` to `codex`, verified in that source's presets.
An optional `toolNames` object replaces that map. Operators must verify additional
tool names against their Git AI version.

Session keys hash the native session ID. Trace keys hash the encoded ASR edit citation.
Namespace collisions remain ambiguous. A served model from the causing inference is
required for a new Git AI entry. Requested models remain labeled as requested in
inspection output. Sessions with several served models are omitted because one Git AI
session entry cannot describe each edit's model. These omissions produce diagnostic
codes. Human entries are read but not synthesized from the session's user label.

Mixed Git AI session, human and legacy keys are read. Key matches only locate candidate
sessions. They supply no ASR line or commit credit. Unknown metadata and exact JSON
numbers survive serialization. No transcripts, statistics or transcript URLs are added.

This is an offline exporter for existing commits. It does not install Git hooks or
maintain Git AI working state during rebases, stashes or resets. Use Git AI for those
operations and export again for a chosen resulting commit when needed.

Malformed complete ASR lines are reported and skipped. Incomplete tails are deferred.
Structural damage disables credit for that file. Unknown records remain available
as raw input. The implementation does not aggregate usage or cost. It does not load
external content or run commands from streams.

The edit comparison is bounded to two million LCS cells. Larger comparisons receive
no attribution. Git output is limited to 32 MiB per operation. Special paths requiring
Git C-string decoding, binary files and ambiguous alignments stay unresolved. Files
with quotes or newlines cannot be written to Git AI notes by this port.

Store loading refuses file symlinks and caps each file at 64 MiB, total bytes at
256 MiB, files at 1,000 and directory depth at 16. Capacity failures stop the report.
See [the threat model](../../SECURITY.md).

## Tests

```sh
bash exporters/git-notes/check.sh
```

Tests use synthetic Git repositories, the repository samples and examples, the
ASR validator, mixed Git AI fixtures and a local mocked GitLab API. No Git AI CLI
installation or hosted GitLab instance was live-tested.
