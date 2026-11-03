# Codex structured export design feedback

Keep a machine-readable local record of messages, tool work and recorded decisions.
Codex's `/export` writes Markdown. This reference adds
`/export --format agent-session PATH` to that command for local saved threads.
It uses the same rollout mapper as the offline archive command below.
Remote workspace exports are rejected because local files do not establish their history.
Existing destination files are never overwritten.

```sh
codex sessions export --format agent-session --session THREAD_ID
codex sessions export --format agent-session --all --output NEW_DIRECTORY
```

This is reference code for design feedback on local export, including
[issue #26740](https://github.com/openai/codex/issues/26740).
Codex does not accept outside code or pull requests.

The mapper retains native messages, tool calls and final results, recorded
settings, tool definitions, approval decisions, model calls and usage.
It places folded results at completion and preserves settings cleared with null.
Wide native numbers are strings. Unknown content stays under its native owner.
Later titles and pull request associations require the archive's annotation files.
The single-file TUI export omits those annotations.

The source cannot establish every served model, approval, edit, setting or copied
history boundary. The header declares these losses. No file contents or current
Git state are read to invent historical facts. Output is ASR 0.1.

Source: <https://github.com/openai/codex> at `6b2a2757de696c2506ee460c49c66a8e2bed65e0`.

Run Rust commands from `codex-rs`.

Focused verification commands:

```sh
cargo test -p codex-session-export
cargo test -p codex-tui structured_export_uses_the_existing_export_command --lib
cargo clippy -p codex-session-export -p codex-tui --all-targets -- -D warnings
cargo fmt -p codex-session-export -p codex-tui --check
```

Current results and limitations are recorded in [refresh.json](refresh.json).
The fixtures are synthetic. No current live inference test is claimed.
