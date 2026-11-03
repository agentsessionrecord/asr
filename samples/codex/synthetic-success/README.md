# Codex successful edit fixture

This fixture is authored synthetic data for the supported 0.163.0 native
profile. It was not captured from a live agent run. All paths, prompts, models
and Git metadata are illustrative. `asr` version 0.1.0 converts `native.jsonl`
to `asr.jsonl` without a sample editor or hand-written ASR records.

The task changes the second line of `file.txt` from `old` to `new` and records a
successful `git diff --check` observation. The linked patch completion records success, and the request carries exact replacement lines.
The source explicitly identifies the human prompt and links the causing call to
its served model. No commit action is recorded.

Run the complete offline check from the repository root:

```sh
cargo test -p asr-cli --test convert_blame -- --nocapture
node tools/validator/bin/asr-validate.js --summary samples/codex/synthetic-success/asr.jsonl
```

The test creates a scratch Git repository, substitutes its recorded path and
baseline commit into the native template, writes the changed file and runs the
fixed test command. It converts and validates the session, commits the edit and
checks that blame resolves line 2 to this session, its prompt and its served
model. It also checks that the external commit earns no session commit credit.
The test does not execute commands taken from transcript content.

Validation has zero errors. Unknown vendor extension warnings are expected.
Codex also retains an unsupported native event as a vendor record, which adds
one unknown-type warning.

SHA-256 values cover exact bytes, including newlines.

| File | SHA-256 |
| --- | --- |
| `native.jsonl` | `f7c4dbdc1542f13cd6b7c65b63c7148f5171fa1c3e0f93c76d668632d6e38e63` |
| `asr.jsonl` | `9d7e3097e12607743e37de388ae84b706c57dab3772d2aec05acdf625eaa65c6` |
