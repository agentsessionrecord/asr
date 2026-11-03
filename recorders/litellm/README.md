# LiteLLM gateway recorder

This Python callback records native Anthropic Messages and OpenAI Responses traffic
through a LiteLLM proxy. It writes one private ASR file per observed agent session.
It supports LiteLLM 1.106.6, Claude Code 2.1.305 and Codex 0.163.0.
Synthetic native requests and responses are in `tests/fixtures/`.

## Install and run

From the repository root:

```sh
uv sync --all-packages
export ASR_OUTPUT_DIR=/private/asr/run-1
# Set LITELLM_MASTER_KEY and ASR_UPSTREAM_AUTHORIZATION in the process environment.
# ASR_UPSTREAM_AUTHORIZATION is the full upstream Authorization header value.
uv run --package asr-litellm litellm --config recorders/litellm/config.example.yaml \
  --host 127.0.0.1 --port 8400 --num_workers 1
```

Set the example's two targets to an endpoint you are allowed to use. Supply
its authorization header through the process environment. Keep credentials out
of the YAML file.
Use one proxy worker. Files have mode 600.
The directory is created with mode 700. Existing output directories must belong
to the current user and have mode 700. Directory symlinks are refused.
A restart creates a suffixed file with the same native session identity, a gap
and a `capture_restart` loss. Earlier files remain unchanged.

Point Claude Code's `ANTHROPIC_BASE_URL` at
`http://127.0.0.1:8400/asr/anthropic`.
Point a Codex custom provider's `base_url` at
`http://127.0.0.1:8400/asr/openai/v1`, with `wire_api="responses"` and
`supports_websockets=false`. Supply the proxy key through the agent's environment.
Use the native pass-through routes in the example. Model routing endpoints that
translate between API formats are outside this callback's supported configuration.

The callback uses LiteLLM's response headers hook to observe the HTTP response
before consumption. It wraps the native byte stream and yields each chunk
unchanged. Completed items are recorded at receipt. It does not wait for the full
response before forwarding bytes. The pre-call hook retains original request
metadata that LiteLLM removes from pass-through requests.

## Mapping

- Codex uses `thread-id`, then `thread_id` or turn metadata, before root session
  headers and cache keys. A native parent thread field supplies the parent link.
- Claude Code uses metadata `agent_id` or the agent header for a child, then
  metadata `session_id`, its older composite suffix, or the session header.
  A child can link to the shared parent session.
- These client values are unauthenticated grouping evidence. Unknown agent
  identities are skipped. `Recorder.ungrouped` counts skipped model requests.
  A known `previous_response_id` can join an incremental request to its session.
- Input history is aligned by occurrence. Repeated history is emitted once.
  Repeated identical messages at distinct positions remain distinct. Rewrites,
  retries and shortened context produce gaps and retain earlier observations.
- Calls and results retain native call IDs. A repeated result is folded once.
  Distinct model calls that reuse a call ID remain ambiguous. Client argument
  rewrites produce a gap and effective input on a later result when available.
- `session_info.tools` replaces the offered tool list when it changes. Function
  parameters and Anthropic input schemas become `inputSchema`. Namespaced tools
  retain their qualified names. Implicit provider schemas declare a `tools` loss.
- System and developer messages have `origin: instructions`. A user role alone
  does not establish human authorship. Model output has `author: model` or
  `requestedBy: model` and links to its inference.
- `is_error: true` means a failed tool result. Other results have `status: unknown`
  unless an explicit native status is present. Error text never establishes a
  denial, exit code, file edit or commit.
- Each completed exchange has an inference with requested and served models,
  sent settings, native IDs, usage and response receipt time. Anthropic input
  totals include cache reads and writes. Responses totals already include cache
  and reasoning. Unknown usage and cost remain absent. Core counts outside the
  safe integer range remain only as exact strings in metadata.
- Only headers needed for mapping and correlation are kept. Other headers and
  unrelated request fields are excluded. Claude thinking is recorded as a
  summary. Secret headers are excluded. Known credential values, token patterns, encoded
  forms and credential fields are scrubbed from content and metadata. Redacted
  records carry `truncated` and declare the loss. Reasoning signatures and opaque
  encrypted bytes are excluded. Encrypted reasoning retains only its visibility.

The gateway declares missing approvals, agent settings, file changes, exit codes,
commits, copy detection, full subagent links, cost, lifecycle, execution times,
authorship, identity, hooks, working directory, full context and content metadata.
It adds newly detected losses with append-only `session_info` records.
It does not infer a session end from a completed model call.

## Limits

This is a single-process recorder. It keeps grouping and history state in memory.
Restarts use a new capture file. The recorder does not coordinate multiple
workers or support WebSockets. Capture failures are counted and logged locally.
They do not reject requests or alter forwarded response bytes.
Active session indexes are capped at 128 and response mappings at 1024.
A capture rotates after 2048 records or 16 MiB. Request observations, SSE frames,
JSON response buffers and history windows are capped at 2 MiB.
A history window holds at most 512 items. Trimming and capture stops write gaps.
Evicted sessions start a suffixed capture if they return. Calls that fail before an
HTTP response reaches the headers hook are outside the observed connection.
Response items lost to cancellation produce gaps when the stream closes.
A hard process termination can leave the last call without terminal evidence.
No gateway can see tools that run after the last request unless their result is
sent through another request. An unmatched call warning leaves its outcome unknown.

The files contain full prompts, tool definitions and model-facing output.
Credential scrubbing does not establish that they are safe to share.

## Checks

```sh
uv run --all-packages pytest recorders/litellm/tests
node tools/validator/bin/asr-validate.js /private/asr/run-1/session.jsonl
```

`scripts/ci.sh` runs the recorder suite. Each file produced by the suite is
checked with the Node validator. Expected unmatched-call warnings in interrupted
or ambiguous fixtures represent unavailable tool outcomes.

`scripts/live.py` runs an isolated scratch task through the local LiteLLM endpoint.
Supply `--upstream-base-url` or `ASR_PROVIDER_BASE_URL` with an explicit loopback
URL for the OpenAI-compatible or Anthropic-compatible endpoint. It also accepts
an agent, a model, an evidence directory, a credential file and the
read-only gateway prototype directory. It compares tool calls, tool results,
models and usage with the prototype on the same forwarded traffic. It stops its
services by PID, deletes scratch configurations and saves a count summary beside
private ASR output. It starts no helper agents and changes no global settings.

## Test status

Live-test status: **partial**.
The current recorder passes offline regression checks. A live run of this
revision is pending.

Thinking returned by Anthropic and OpenAI reasoning summaries use summary
visibility. Empty thinking uses omitted visibility and carries no text.
Encrypted thinking carries no provider state or signatures. API traffic does
not establish the agent's cwd or repository. The gateway's own cwd cannot supply
those session facts.
