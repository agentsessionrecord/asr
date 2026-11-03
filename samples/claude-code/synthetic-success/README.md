# Claude Code successful edit fixture

This fixture is authored synthetic data for the supported 2.1.305 native
profile. It was not captured from a live agent run. All paths, prompts, models
and Git metadata are illustrative. `asr` version 0.1.0 converts `native.jsonl`
to `asr.jsonl` without a sample editor or hand-written ASR records.

The first Edit replaces `unchanged\nold` with `unchanged\nnew` in `file.txt`.
Both strings span two lines and have no trailing newline. Each Edit result
explicitly records `originalFile: null`. The session then creates `created.py`
with Write, inserts a header while changing its first value, and edits its last
line. These edits shift the surviving Write lines. Native results retain the
parent and source assistant links. A final `git diff --check` result records
success. No commit action is recorded.

The source explicitly identifies the human prompt and links each causing call
to its served model. The unchanged first line stays unknown. The final changed
lines have these edit citations:

| File | Lines | Call |
| --- | --- | --- |
| `file.txt` | 2 | `edit-1` |
| `created.py` | 1 and 2 | `shift-1` |
| `created.py` | 3 and 4 | `write-1` |
| `created.py` | 5 | `tail-1` |

Run the offline checks from the repository root:

```sh
cargo build -p asr-cli --locked
python3 -I -S plugins/hooks-core/tests/check_blame.py --binary target/debug/asr
cargo test -p asr-cli --test convert_blame -- --nocapture
node tools/validator/bin/asr-validate.js --summary samples/claude-code/synthetic-success/asr.jsonl
```

The Python check creates a scratch Git repository, substitutes its path into
the native template and applies the recorded Write and Edit arguments. It
captures the same events through the hook recorder, converts the native sample
and compares it with the expected ASR. It commits the edits and checks every
final line through both capture paths. Each path matches six lines to the right
call and leaves one unchanged line unknown. Converted lines also resolve to
their human prompt and served model. The external commit earns no session
commit credit. The check runs only the fixed Git commands it defines.

Validation has zero errors. The converted sample has one unknown vendor
extension warning. Hook capture has one unknown extension warning and 17
unknown vendor record warnings. The vendor records preserve hook observations.

SHA-256 values cover exact bytes, including newlines.

| File | SHA-256 |
| --- | --- |
| `native.jsonl` | `906687da95b14fdb16db26103cbb75dc56daca2448d992fa2ab903857272d371` |
| `asr.jsonl` | `6d1b3d91df0783e381f13688acd44ffc067ea31b9654420b95d800b4bb3e00a8` |
