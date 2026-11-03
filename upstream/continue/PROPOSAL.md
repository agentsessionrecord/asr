# Continue native Agent Session Record export

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

Applies to upstream commit `5522c6f44ca0ac3528b37244818fbfa39b5af470`.
The local patch adds a CLI command using Continue's native `Session` type.

```sh
git am patches/0001-native-agent-session-export.patch
cn sessions export --format agent-session --session SESSION_ID
cn sessions export --format agent-session --output ./exports
cn sessions export --format agent-session --source ./native-sessions --output ./exports
```

Exactly one selected session is required for standard output. An output directory
receives one file per selected session, with a SHA-256 filename derived from its
native identity. The header retains the identity. An omitted selection exports
all stored sessions when an output directory is supplied. The source defaults
to the sessions directory under `CONTINUE_GLOBAL_DIR` or the normal Continue home.
The command reports missing, corrupt and duplicate native identities as failures.
It reads saved session identities instead of interpreting supplied IDs as paths.
It does not select remote sessions or implement `--since`.

The exporter writes ASR 0.1 with `producer.method: "native"`. It preserves native
message order and exact text. It records tool requests and model-facing results.
Repeated results are folded at their final stored position. Unknown outcomes stay
unknown. It keeps recorded reasoning text and excludes opaque provider state.
It does not fetch links or read current files to reconstruct earlier work.

The patch declares missing approvals, policy history, offered tools, inference
settings, model-call boundaries, usage history, file changes, commits, subagents,
copies, instructions and native metadata. It does not infer model calls from
assistant replies or infer edits and commits from prose. User roles do not prove
human authorship. The patch uses deterministic record IDs where native IDs are
unavailable or collide. It rejects unsafe parsed numbers rather than rounding
native tool arguments. Quoted wide values stay strings.

Credential fields and common token forms are filtered. Affected records carry
`truncated: true` and the session declares `secrets` missing. Filtering and valid
ASR do not establish that a transcript is suitable to share.

This patch adds export only. Live ASR files, discovery registration, deletion
hooks, annotations and complete capture of historical settings are not included.
It needs no added production dependency. The fixture is synthetic.

The export retains cumulative `Session.usage` totals in a tail `session_info`.
Native prompt and completion totals already include cache and reasoning counts.
The native total cost is a harness estimate. Missing child scope stays unknown.
Stored mode and title snapshots also go at the tail. The recorded workspace path
is retained when absolute. Tool outcomes come from a unique native tool state.
Approval outcomes are not inferred from those states. Effective rewritten
arguments are retained when the saved tool state supplies them. Raw requested
argument strings remain exact, including wide JSON numbers. Destructive CLI
compaction has one summary and a following gap. Images with remote URLs are not
fetched and their omission is declared.

## Validation

Fourteen focused exporter and command tests pass. A focused type check against
the native `Session` declaration passes. Transitive implementation imports from
that declaration are excluded from this type check. A complete source CLI build
was not attempted because the task changes only export code.
The packaged native fixture is replayed and its ASR sample validates with zero
errors and warnings.

An installed Continue CLI 1.5.47 scratch turn against a local OpenAI-compatible endpoint completed
without an account. The new export command function exported its saved native
session. The stream had 4 records, zero errors and zero warnings. The full patched
CLI entrypoint was not used for this live run. The command registration is tested
with Commander. The run used an isolated home and configuration and disabled
nonlocal network access. Runtime credentials and logs are not packaged.

```sh
cd extensions/cli
npm test -- src/agent-session.test.ts src/commands/sessions.test.ts
```

## Verification scope

The live evidence above is from a prior revision. The current source has focused
regressions and package checks. Its full agent and model path has not been rerun.
