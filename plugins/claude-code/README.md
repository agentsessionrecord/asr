# Claude Code ASR recorder

This passive recorder writes one append-only ASR file per native session. It
uses 2.1.305. Python 3.11 or later and a POSIX host are required.
The shared [JSON hook core](../hooks-core/README.md) documents capture policy,
limits, storage and the adapter pattern.

## Install and uninstall

Run from the repository root. Choose private capture and install directories.
The installer merges its registrations into the selected native configuration.
It keeps other hooks and settings. Restart the agent after setup.

```sh
python3 plugins/hooks-core/install.py claude-code \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$HOME/.claude/settings.json" \
  --output-dir "$HOME/.local/share/asr-captures"
```

Metadata is the default. Add `--content full` to retain available prompt,
reply, input and output text with known-secret exclusion. Keep the output
private. Read the shared core's capture policy before enabling full content.

```sh
python3 plugins/hooks-core/install.py claude-code \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$HOME/.claude/settings.json" --uninstall
```

Uninstall removes this prefix's registrations and retains capture files. Remove
the installed files only after disabling all agents that use the shared prefix.

## Mapping and limits

The installer also creates a local plugin at `<prefix>/claude-code`. Omit
`--config` when preparing that plugin. Start Claude with
`claude --plugin-dir <prefix>/claude-code`. Choose either settings hooks or the
local plugin for each run to avoid duplicate callbacks. Uninstall the local
plugin by omitting `--plugin-dir` on later runs.

This adapter folds PostToolUse and PostToolUseFailure with PostToolBatch. It
keeps final effective input on the result. MessageDisplay chunks concatenate
exactly. PermissionRequest does not state a decision. PermissionDenied states a
denial but can lack a reviewer verdict. Native lifecycle receipt times can set
start and end fields. Subagent stop does not establish session end.

Full-content capture observes the repository at an explicit new session start.
It retains cwd, the Git root and available branch, HEAD and credential-free origin
remote. A missing Git executable or a non-repository cwd does not stop capture.
A resumed session keeps the original header.

Structured PostToolUse results for Write, Edit and MultiEdit produce file changes
at that observation. Write success distinguishes new files from updates. Edit
and MultiEdit keep replacement strings. A string originalFile supplies the full
before state. Staged changes remain proposed. Failed outcomes and request-only
observations never establish an applied change. The recorder reads no file
contents to reconstruct edit evidence. Unknown edit forms remain unnormalized.

## Evidence and checks

Official [hook reference](https://code.claude.com/docs/en/hooks), checked 2026-11-01.
Synthetic payloads are in [fixtures/hooks.json](fixtures/hooks.json). These are
authored protocol examples and contain no real sessions. Fields not supplied by
the documented contract remain unknown. The shared suite tests this adapter and
validates every generated ASR stream:

```sh
bash plugins/hooks-core/check.sh
```

The isolated live test covers Claude Code 2.1.305 with an allowed command, a
refused command, a hook rewrite and an edit in a scratch Git repository. After
a local commit, `asr blame` resolves the changed line to that session. See [live-test.json](live-test.json) for
counts and checks. It starts no subagents and changes no global config.
