# Mistral Vibe ASR recorder

This recorder uses Vibe's native `pre_tool`, `post_tool` and `post_agent`
command hooks. See [shared capture rules](../python-core/README.md).

Install into the Python environment used by the hook commands:

```sh
uv pip install ./python/agent_session_record ./plugins/python-core ./plugins/mistral-vibe
```

Merge `hooks.toml` into the project's `.vibe/hooks.toml` or the Vibe home
directory's `hooks.toml`. Replace each command with the absolute path to that
environment's Python and this plugin's `record.py`. Keep `strict = false`.
Place the post-tool recorder after other post-tool hooks to capture their
output rewrites. Set `ASR_OUTPUT_DIR` before starting Vibe. Set
`ASR_CONTENT=full` to retain available content.

To uninstall, remove the three `asr-` entries from `hooks.toml` and run
`uv pip uninstall asr-mistral-vibe` in the hook environment. Existing files
stay in the output directory.

The mapping follows Vibe `3.0.4`, source commit `338ad4bf0f`. The native payload builders live in
`harness/runtimes/python/python/mistralai_vibe_local_harness/vibe/_foreign_hooks.py`.
Registration comes from `vibe/core/hooks/models.py` and `config.py`.

Tool names stay qualified, such as `file_system.bash`. Native tool_call_id
pairs requests and results. Pre-tool input stays a request under `_meta`.
Effective post-tool input goes on the result. Explicit `tool_status` values
`success` and `failure` become completed and failed. A nonzero shell exit can
still be a successful tool invocation. The structured output stays in metadata
and the current tool_output_text supplies content.

The documented duration_ms is a placeholder zero. It is omitted. Post-agent
is a turn review and can trigger another attempt. It does not set endedAt.
No session start or end event is exposed by these hooks, so capture starts
with a gap. A supplied parent_session_id establishes a child relationship.

Other hooks may short circuit execution or rewrite output after observation.
This command cannot see their final decisions, approvals or automatic reviewer
verdicts. Those facts, complete output, lifecycle and execution durations are
declared missing. A supplied agent_name is kept verbatim as mode without
deriving approval or sandbox policy.

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
