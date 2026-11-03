# Pi native Agent Session Record export

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

Adds an offline export binary without loading extensions, provider settings or the agent runtime. The package bin metadata and generated install lock include it.

Applies to [https://github.com/badlogic/pi-mono](https://github.com/badlogic/pi-mono) at `a14cdf90f0a76532f3e20bc3c01872837cef24ba`. The local patch commit is `e39eebeb213f17f715d8d56492b5c628c58aadb8`.

Apply the patch with `git am patches/0001-native-agent-session-export.patch` in a clean checkout of that base.

```text
pi-session-export --session samples/native/native.jsonl --format agent-session --output session.asr.jsonl
```

It records the native tree in file order, including abandoned branches. It preserves exact text, reasoning summaries when the recorded provider establishes
them, other reasoning text without a visibility claim, tool calls, final tool results, compaction summaries and injected messages. Identified assistant settlements supply inference records with separate requested and served model identities. Native response IDs are retained. Input usage includes cache subsets. Reported zeroes remain zeroes and cost provenance stays explicit.

Local failed assistant settlements without provider identity do not create inference records. Media and opaque signatures are excluded. Approvals, file changes, commits and child-session lineage are not reconstructed. Unsafe native integers remain exact strings, with unsafe core usage stored only in namespaced metadata. Unsupported or corrupt source files fail before output.

Supported source: Pi native session tree version 3 at this revision. Output uses ASR `0.1` and `producer.method: "native"`. File output is exclusive and private where the command writes a file.

Checks: 6 focused Node tests. Full required npm check, including typecheck and browser smoke. Generated coding-agent install-lock check. The included native fixture and sample are synthetic. The sample passes the reference validator with zero errors.

An isolated source CLI run against a local OpenAI-compatible endpoint exported 9 records, including 2 inference records, a tool call and a result. Validation reported zero errors or warnings. The provider key was read from private provider settings. The generated model catalog was hydrated locally and is not part of this patch.

`manifest.json` pins the upstream base, local commit and packaged file hashes. Run `node upstream/pi/check.mjs` from the ASR repository to check this patch package without upstream dependencies.

## Verification scope

The live evidence above is from a prior revision. The current source has focused
regressions and package checks. Its full agent and model path has not been rerun.
