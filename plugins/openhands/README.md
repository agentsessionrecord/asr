# OpenHands ASR recorder

This recorder uses command hooks from the OpenHands SDK `HookConfig` API.
See [shared capture rules](../python-core/README.md).

Install into the Python environment used by the hook commands:

```sh
uv pip install ./python/agent_session_record ./plugins/python-core ./plugins/openhands
```

Merge `hooks.json` into `.openhands/hooks.json` in the project or user directory.
Replace every command with the absolute path to that environment's Python
and this plugin's `record.py`. For SDK applications, pass the result of
`HookConfig.load(...)` as `hook_config` when constructing the conversation.
Set `ASR_OUTPUT_DIR` before running it. Set `ASR_CONTENT=full` to retain
available content. Keep these hooks synchronous to preserve receipt order.

To uninstall, remove these recorder commands or the recorder's HookConfig
entries and run `uv pip uninstall asr-openhands` in the hook environment.
Existing recordings stay in the output directory.

The mapping follows SDK `1.42.1`, source commit `98338ff`. The contract is in
`openhands-sdk/openhands/sdk/hooks/types.py`, `config.py`, `manager.py` and
`conversation_hooks.py`.

HookEvent supplies `event_type`, session identity, tool name, input, response
and message text. It does not supply the action ID or tool call ID used by
the conversation event system. Calls receive derived IDs. Results have no
callId and remain unpaired. Even identical repeated inputs cannot be joined.
The validator's unpaired-call and unpaired-result warnings are expected.

The hook response is a structured observation rather than the final LLM
representation. It is kept under `_meta.observedResponse`. Status remains
unknown because HookEvent has no general outcome field. A response or exit
code does not become an approval decision. Other hooks' outcomes and
confirmation decisions remain unavailable to this recorder.

SessionStart and SessionEnd set receipt lifecycle times. Stop does not end the
session. UserPromptSubmit preserves the supplied message without guessing who
wrote it. Native callback/event APIs could add broader coverage in another
adapter, but this command does not borrow their facts from persisted logs.

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
