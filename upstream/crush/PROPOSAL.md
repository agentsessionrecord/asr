# Crush native Agent Session Record export

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

Adds an offline export command beside the existing session commands. It uses the native session and message services.

Applies to [https://github.com/charmbracelet/crush](https://github.com/charmbracelet/crush) at `b576f95896704c88ed84b2f16c3c346d6c58cb42`. The local patch commit is `794e53e86087dd945473bb044a57ffeceda9ad50`.

Apply the patch with `git am patches/0001-native-agent-session-export.patch` in a clean checkout of that base.

```text
crush sessions export --session SESSION_ID --format agent-session --output exports
```

It records retained text, readable reasoning, tool calls and final tool results in native row and content order. It exports the complete retained store snapshot and marks compaction summaries. Tool arguments keep integers beyond JavaScript precision as strings.

It omits mutable titles without an observation time, row-level message timestamps, media data, provider metadata, aggregate model accounting, approvals, tools, file changes and commits. It cannot restore deleted database history or derive event ordering hidden by mutable rows. Unknown prompt authors stay unknown.

Supported source: the native SQLite message store at this revision. Output uses ASR `0.1` and `producer.method: "native"`. File output is exclusive and private where the command writes a file.

Checks: 2 focused exporter tests and matching session-setup tests. Go vet for the exporter. Go formatting. Synthetic fixture created through the real SQLite services. The included native fixture and sample are synthetic. The sample passes the reference validator with zero errors.

An isolated source binary run through the local Responses endpoint exported 5 records, including one tool call and one result. Validation reported zero errors or warnings. The provider key was read only from a private provider settings file.

`manifest.json` pins the upstream base, local commit and packaged file hashes. Run `node upstream/crush/check.mjs` from the ASR repository to check this patch package without upstream dependencies.

## Verification scope

The live evidence above is from a prior revision. The current source has focused
regressions and package checks. Its full agent and model path has not been rerun.
