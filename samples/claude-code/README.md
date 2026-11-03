# Claude Code sample

Agent version: Claude Code 2.1.305. The synthetic task created `hello.txt` containing `hello ASR` followed by LF, read it back and replied `Done.` It ran with isolated home, XDG and agent configuration, a minimal system prompt and only Write and Bash tools. Model access used a configured endpoint. No credential is part of the sample.

The native sample was edited to replace the temporary home path with
`/work/claude`, including recorded text. Its bytes remain unchanged here.
The ASR was regenerated from that curated native input with `asr` version 0.1.0.
The edited ASR producer is `asr-sample-editor` version `1.1`, with method
`converter` and source `agent-session-record-0.1`. Its header links the previous
edited ASR bytes with `derivedFrom.sha256` and declares `sample_paths`.
Records carry `truncated: true` because their source is the edited sample.

The structured Write result establishes success even though it omits `is_error`.
Empty thinking is omitted reasoning. The SDK prompt stays without a human author
because SDK input alone does not establish a person. Native `cwd` and `gitBranch`
supply repository context. These files demonstrate transcript conversion.

The [authored successful edit fixture](synthetic-success/README.md) also checks
conversion and Git line attribution without a live agent request.

Validate the ASR from the repository root:

```sh
node tools/validator/bin/asr-validate.js --summary samples/claude-code/asr
```

SHA-256 values cover exact data file bytes, including newlines.

| File | SHA-256 |
|---|---|
| `asr/session.jsonl` | `4c46b337681f80b72d51b70e7d9eca4e1e2090dfe85a1555276d81115bacc27f` |
| `native/session.jsonl` | `f5eec034d3c61ef725e3a23a9e83a1dd65ccc4afae0030b1a878eefa87d64957` |
| `synthetic-success/native.jsonl` | `906687da95b14fdb16db26103cbb75dc56daca2448d992fa2ab903857272d371` |
| `synthetic-success/asr.jsonl` | `6d1b3d91df0783e381f13688acd44ffc067ea31b9654420b95d800b4bb3e00a8` |

Validation reports zero errors. 22 warnings identify the declared vendor extension and 21 native vendor records.
