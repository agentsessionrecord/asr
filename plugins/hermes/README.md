# Hermes ASR recorder

This plugin observes Hermes tools, approval responses, turn boundaries and
session boundaries. It never returns a tool directive or modifies arguments.
See [shared capture rules](../python-core/README.md) for storage, content and
safety limits.

Install from the ASR repository root into the Hermes Python environment:

```sh
uv pip install ./python/agent_session_record ./plugins/python-core ./plugins/hermes
hermes plugins enable asr-recorder
export ASR_OUTPUT_DIR=/absolute/path/to/records
export ASR_CONTENT=full
```

Restart Hermes after setting the environment. The package uses the normal
`hermes_agent.plugins` entry point. A directory installation can instead copy
`__init__.py` and `plugin.yaml` into the profile's `plugins/asr-recorder/`
directory after installing the Python packages. Enable the same plugin name.

To uninstall, disable the plugin, remove its directory if one was copied, and
remove the adapter package from the Hermes environment:

```sh
hermes plugins disable asr-recorder
uv pip uninstall asr-hermes
```

Restart Hermes. Existing recordings stay in the configured output directory.

The mapping follows Hermes observer schema `hermes.observer.v1`, source commit
`c7c7e0fa92`. Its contract is in
`website/docs/developer-guide/observer-hooks.md`. Tool dispatch and approval
fields were checked against `agent/tool_executor.py`,
`agent/inline_tool_executors.py`, `hermes_cli/plugins.py`,
`tools/approval_context.py`, `tools/approval_gateway_wait.py` and
`tools/approval_smart.py`.

`pre_tool_call` records a request. `post_tool_call` supplies effective input and
maps explicit `ok`, `error`, `blocked` and `cancelled` statuses. Other statuses
stay unknown. A blocked outcome alone does not identify a hook decision.
Later result transformers can change model-facing output, so output and hook
rewrites remain declared losses.

Only `post_approval_response` creates an approval. Choices `once`, `session`
and `always` use their native grant lifetime. `deny` is a user denial unless
the hook states `coalesced=true`. Coalesced responses reuse another call's
decision and use `by=policy`. The native coalesced flag is retained.
`timeout` and `cancelled` have no answerer. Explicit smart approval verdicts
with `decided_by=aux_llm` use `by=classifier`. Requests and successful tools
do not become approvals. Other reused grants and hook outcomes may be absent.

`on_session_start` can set the receipt start time. `on_session_end` describes
one run and is kept as an event. Only finalize or reset closes the observed
session identity. Child starts with explicit parent and child session IDs
create a separate child stream with a parent reference. No child agent is
started by this plugin.

Synthetic hook input and ASR are in `fixtures/`. Live-test status is recorded in
the root registry and the implementation report.

## Tests and status

Run from the repository root after installing the validator dependencies:

```sh
uv run --all-packages pytest plugins/python-core/tests
```

The shared suite replays this adapter's synthetic payloads and validates its
ASR output. Live-test status: **partial**.
The current recorder passes offline regression checks. A live run of this
revision is pending.
