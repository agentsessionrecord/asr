# AstrBot ASR recorder

This is an AstrBot event plugin. It observes requests, tool callbacks and agent
completion. It records the conversation ID from `ProviderRequest.conversation`.
It skips events without that identity. See
[shared capture rules](../python-core/README.md).

Install the Python packages from the ASR repository root into AstrBot's Python
environment:

```sh
uv pip install ./python/agent_session_record ./plugins/python-core ./plugins/astrbot
```

Create `data/plugins/astrbot_plugin_asr_recorder/` in the AstrBot installation.
Copy `main.py` and `metadata.yaml` there. Set `ASR_OUTPUT_DIR` before starting
AstrBot. Set `ASR_CONTENT=full` to retain available content. Restart AstrBot
and enable the plugin in its normal plugin manager.

To uninstall, disable the plugin, remove that plugin directory, run
`uv pip uninstall asr-astrbot` in its environment and restart AstrBot.
Existing recordings stay in the output directory.

The mapping follows source commit `3d92821`. Native signatures come from
`astrbot/core/astr_agent_hooks.py` and
`astrbot/core/star/register/star_handler.py`. Execution behavior comes from
`astrbot/core/agent/runners/tool_loop_agent_runner.py`.

The tool hooks omit native call IDs. Calls receive derived IDs, and results
stay unpaired. Names, argument equality and callback proximity do not establish
pairing. The start callback sees filtered arguments. The end callback can see
the original unfiltered request. Neither is asserted as final effective input.
The MCP result's explicit `isError` supplies status when available.

The tool loop may serialize or extend content after the callback. This plugin
keeps the callback representation and declares incomplete model-facing output.
Agent begin and done events are run boundaries. They do not establish the
start or end of a persisted conversation. Permissions, policy changes, model
calls, delegated-session identity and other plugins' decisions are unavailable
through these registrations. They remain declared losses.

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
