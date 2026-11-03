# Deep Agents ASR recorder

This recorder uses the bundled Deep Agents Code command hooks. It covers the
server tool hooks and the client lifecycle hooks when both sides load the
configuration. It does not instrument arbitrary Deep Agents SDK applications.
See [shared capture rules](../python-core/README.md).

Install into the Python environment used by the hook commands:

```sh
uv pip install ./python/agent_session_record ./plugins/python-core ./plugins/deepagents
```

Merge `hooks.json` into the project's `.deepagents/hooks.json`, or into the
user's Deep Agents configuration directory. Replace every example command
with the absolute path to that environment's Python and this plugin's
`record.py`. Keep the commands synchronous to preserve receipt order. Set
`ASR_OUTPUT_DIR` in the client and server environments. Set `ASR_CONTENT=full`
to retain available content.

To uninstall, remove these recorder commands from the hooks configuration and
run `uv pip uninstall asr-deepagents` in the hook environment. Existing files
stay in the output directory.

The mapping follows source commit `e9f0d88`, bundled Code version `0.2.2`.
The native contract is in `libs/code/deepagents_code/hooks/models/wire.py`.
Configuration and execution were checked in `hooks/loading.py`,
`hooks/projection.py` and `hooks/server_middleware.py` under that package.

Pre-tool input is a request. Post-tool input is learned at completion and goes
on the result under ASR-076. A native `tool_use_id` pairs the call and result.
`PostToolUse` is completed. `PostToolUseFailure` is failed or explicitly
interrupted. A permission request does not carry a person's choice. No approval
is inferred. The effective wire `permission_mode` is preserved verbatim as an
approval setting without deriving whether it asks a person.

An explicit new-session startup can set `startedAt`. SessionEnd can set
`endedAt`. Stop and SubagentStop do not close a session. Other hook decisions,
later output rewrites and subagent parentage are not visible to this command.
Their absence remains declared in `missing`. The recorder does not read
transcripts or checkpoints to fill these gaps.

Synthetic hook input and ASR are in `fixtures/`. The root registry records the
live-test status.

## Tests and status

Run from the repository root after installing the validator dependencies:

```sh
uv run --all-packages pytest plugins/python-core/tests
```

The shared suite replays this adapter's synthetic payloads and validates its
ASR output. Live-test status: **partial**.
The current recorder passes offline regression checks. A live run of this
revision is pending.
