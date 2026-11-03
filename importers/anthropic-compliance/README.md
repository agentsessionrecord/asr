# Anthropic Compliance transcript importer

Convert saved Claude Code local transcript pages from the Anthropic Compliance
API into one ASR session. The importer reads local files and makes no API calls.

Status: not live-tested. Fixtures are synthetic and shaped from the official
local session documentation retrieved on 2026-11-01. That page has no schema
version. Remote sessions and other product surfaces are outside this profile.

## Install and use

From the repository root, with Python 3.11 or later and uv:

```sh
uv sync --all-packages
uv run --all-packages asr-import-anthropic-compliance page-1.json page-2.json \
  --output session.jsonl
node tools/validator/bin/asr-validate.js session.jsonl
```

Supply saved pages from one oldest-first pagination walk, in returned order.
The response must contain `session` and `data`.
The session must have `type: compliance_local_session` and
`product_surface: claude_code`. Native `session.id` supplies the ASR identity.
Use `--namespace` only when source session IDs repeat across installations.
The output must be a new file. Page overlaps are deduplicated by native message
ID. Conflicting observations become gaps. A remaining `next_page` cursor at the
end produces a gap. The importer never follows a cursor or link.

## Mapping

| Source | ASR |
| --- | --- |
| `session.id`, `session.user` | Session identity and sourced account identity |
| Message `id`, `created_at`, `role` | Record identity, event time and role |
| Ordered `text` blocks | Ordered messages with exact text |
| `tool_use.id`, `name`, JSON string `input` | Tool call with native join key and arguments |
| `tool_result.tool_use_id`, `is_error`, `content` | Paired result and explicit outcome |
| `truncated` | Shortened record and declared content loss |
| `content_unavailable` provenance | Empty shortened message and a positioned gap |
| `synthetic_marker` provenance | Harness notice and a gap for replaced content |
| `client_asserted` provenance | Unverified content without model authorship |

Provenance and model labels stay in record metadata.
Verified assistant content can identify model authorship.
A user role does not establish human authorship.
Truncated tool input stays in `inputText` and is never parsed as JSON.
An untruncated invalid JSON input is retained as text with a gap.
Session `created_at` names the earliest retained call, so it is kept as metadata.
Neither it nor `updated_at` establishes session lifecycle times.

The documented transcript does not identify individual model calls.
Model labels therefore do not create inference records or guessed usage.
Approvals, reasoning, tool definitions, agent settings, exit codes, edit evidence,
commit actions, subagent links and copy boundaries remain declared losses.
Tool input and reply text do not establish applied edits or commits.
See the [shared safety rules](../vendor-core/README.md#safety-and-losses).

## Tests and sources

```sh
uv run --all-packages pytest importers/anthropic-compliance/tests
```

The [native fixture](tests/fixtures/local-page.json) covers verified and asserted
messages, tool pairing, markers and retention loss.
The [ASR sample](tests/fixtures/local-page.expected.asr.jsonl) is its output.
Tests also cover pagination overlap, missing pages and truncated arguments.
Warnings from unpaired calls or results describe missing source evidence.

Source: [Retrieve session transcripts](https://platform.claude.com/docs/en/manage-claude/compliance-sessions).
