# Codex sample

Agent version: Codex CLI 0.163.0. The original producer was the Codex native exporter, `codex` version `0.0.0`, with method `native` and source `codex-rollout`.

An isolated synthetic task read `example.txt` with a shell command and attempted to use `apply_patch` to create `result.txt` containing `synthetic sample complete.` The initial input file contained `synthetic sample` followed by LF. The run used an empty home and agent configuration, model `MODEL`, low reasoning effort, approval policy `never` and a workspace-write sandbox through an OpenAI-compatible or Anthropic-compatible endpoint.

The retained rollout was curated for this sample. The client label is
`sample-client`, and two stock instruction phrases were shortened. Temporary
paths and session IDs belong to the synthetic run. Native bytes remain unchanged
here. The ASR was regenerated with `asr` version 0.1.0 from that curated input.
Its producer is `asr-sample-editor` version `1.1`, with method `converter` and
source `agent-session-record-0.1`. The header declares `sample_text` and links the
previous edited ASR bytes with `derivedFrom.sha256`. Records carry
`truncated: true` because their source is the edited sample.

The original environment blocked its attempted edit. Its output does not supply
successful-edit evidence. The [authored successful edit fixture](synthetic-success/README.md)
separately checks conversion and Git line attribution without a live request.

Validate the ASR from the repository root:

```sh
node tools/validator/bin/asr-validate.js --summary samples/codex/asr
```

SHA-256 values cover exact data file bytes, including newlines.

| File | SHA-256 |
|---|---|
| `asr/session.jsonl` | `f9b8b80104df3b5d49526b27a439ad133f5a34d7d1d1b6637cf95f1e5505b76d` |
| `native/session.jsonl` | `6cf65a8a424347b0e185c14e62e85b16155b9857dd9b8f787e036912b44d952f` |
| `synthetic-success/native.jsonl` | `f7c4dbdc1542f13cd6b7c65b63c7148f5171fa1c3e0f93c76d668632d6e38e63` |
| `synthetic-success/asr.jsonl` | `9d7e3097e12607743e37de388ae84b706c57dab3772d2aec05acdf625eaa65c6` |

Validation reports zero errors. Nine warnings identify the declared vendor extension, seven native vendor records and one tool whose native name was not retained.
