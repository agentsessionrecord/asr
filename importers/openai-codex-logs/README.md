# OpenAI Codex compliance log importer

Convert one session of saved `CODEX_LOG` JSONL records into ASR.
This command only reads local files.

Status: not live-tested. Official OpenAI documentation confirms the logs platform
and Codex event coverage, but does not publish the payload schema used here.
This is an explicit compatibility profile based on Elastic's documented raw
Codex log fields and synthetic pipeline examples retrieved on 2026-11-01.
It does not claim support for every Enterprise export or `conversation_message`.

## Install and use

From the repository root, with Python 3.11 or later and uv:

```sh
uv sync --all-packages
uv run --all-packages asr-import-openai-codex-logs codex-logs.jsonl \
  --output session.jsonl
node tools/validator/bin/asr-validate.js session.jsonl
```

Partition logs by native `event_details.session_id` before importing.
Mixed session IDs are rejected. `--session-id` can supply an independently known
native ID when damaged input lacks one. Events without a session join key remain
unattributed metadata gaps. `--namespace` is available when native IDs repeat.
The output must be a new file. Input order is retained even when times disagree.

## Mapping and limits

| Raw source shape | ASR |
| --- | --- |
| `type: CODEX_LOG`, `event_details.session_id` | Codex session identity |
| `event_id`, `timestamp`, `turn_id` | Native or derived record ID, event time and turn |
| `PROMPT_RESPONSE_RECEIVED` prompt and response text | Messages without guessed authorship |
| `TOOL_CALL_COMPLETED` with `tool_call_id` | Call snapshot immediately before its result |
| Tool name and `tool_input` | Native tool name and received arguments |
| Tool status `success`, `failed`, `error`, `denied`, `cancelled` | Explicit result status |
| Recorded `decision: approved` or `denied` with `call_id` | Approval at its own source position |
| Other payloads and unknown values | Metadata with a positioned gap |

The additional approval encodings `approved_for_session` and `timed_out` map to
a session grant and cancellation. No decider is guessed.
There is no live confirmation of these encodings in Enterprise exports.
Unfamiliar encodings stay in metadata.

Elastic defines `call_id` as an MCP or tool call identifier.
It does not establish an individual model-call boundary.
Model labels, reasoning effort, service tier, usage and errors therefore remain
in metadata. They do not create inferences, session totals or cost claims.
The completion timestamp belongs to the result. A call discovered only in that
snapshot has no invented request timestamp.

The profile lacks complete approval history, copy boundaries, subagent lineage,
reasoning, offered tools, agent settings, tool output, exit codes and edit or
commit evidence. Those limits are listed in `missing`.
See the [shared safety rules](../vendor-core/README.md#safety-and-losses).

## Tests and sources

```sh
uv run --all-packages pytest importers/openai-codex-logs/tests
```

The [native fixture](tests/fixtures/codex-logs.jsonl) is synthetic.
The [ASR sample](tests/fixtures/codex-logs.expected.asr.jsonl) shows the mapping.
Tests cover unknown events, malformed lines, incomplete tails and mixed sessions.

- [Official governance and Codex coverage](https://learn.chatgpt.com/docs/enterprise/governance)
- [Official logs platform download guide](https://developers.openai.com/cookbook/examples/chatgpt/compliance_api/logs_platform)
- [Elastic integration fields](https://www.elastic.co/docs/reference/integrations/openai_chatgpt_enterprise)
- [Elastic pipeline fixtures](https://github.com/elastic/integrations/tree/main/packages/openai_chatgpt_enterprise/data_stream/codex_log/_dev/test/pipeline)
