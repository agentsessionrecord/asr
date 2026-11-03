# ACP recorder

This stdio proxy records an ACP client and agent connection as ASR.
It forwards every wire line unchanged. It never runs commands from recorded content.
The mapping targets schema v2.0.0-alpha.9 and supports v1 chunk notifications.
The [ACP guide](../../guides/acp.md) describes the mapping.
Synthetic native traffic is in `tests/fixtures/v2.traffic.jsonl`.

## Install and run

From the repository root:

```sh
uv sync --all-packages
uv run asr-acp --output /private/asr --agent opencode -- opencode acp
```

Configure your ACP client to launch this command in place of its agent command.
Use a registered agent name or a reverse-DNS name controlled by that agent's maintainer.
The recorder takes the version from the initialize response.
It uses ACP session IDs verbatim and hashes them for filenames.
New directories have mode 700 and files have mode 600.
Existing output directories must belong to the current user and have mode 700.
Directory symlinks are refused. Use one recorder process per output directory.

Use `--secret-file /private/credential` to exclude a known credential value.
Repeat the option for other known secret values or secret prompt answers.
The proxy also excludes credential fields, known token patterns and opaque reasoning state.
Wire traffic still reaches the intended peer unchanged.
Scrubbing a recording does not make it safe to share.

Only configure a provider key alongside its approved endpoint in a private file
that the agent reads. The recorder does not configure agent providers.
The live test script checks the agent's resolved endpoint before sending a prompt.
It uses a scratch provider file and removes the runtime after validation.

```sh
uv run python recorders/acp/scripts/live.py --agent-bin /scratch/bin/opencode \
  --key-file /private/provider-key --model "$ASR_OPENAI_MODEL" --base-url "$ASR_OPENAI_BASE_URL"
```

## Mapping and limits

Messages and thoughts fold by message ID. Text chunks concatenate exactly.
Full content replaces chunks. Null clears content and other nullable fields.
Metadata patches replace individual top-level keys.
Idle, requires-action, close and disconnect flush buffered messages at receipt.
A cancellation marks the buffered message interrupted.
An idle state and end of file do not end the session.
Only a successful explicit close records `endedAt`.

A running or final tool status closes its request input.
Pending input stays buffered. A final status writes one result.
Later input changes go on the result. Tool content wrappers are unwrapped.
Display content is not claimed to be verified model input.
A single-file Git patch stays byte-exact on its file change.
Multi-file patches stay in metadata. File changes retain the structured paths
and operations. A final completed call establishes applied status.
A failed call establishes failed status. Cancelled edits remain unknown.
V1 diff payloads remain metadata and declare missing normalized file changes.

Permission responses join to their own request options.
Allow and reject options become separate approval records at response receipt.
Unknown choices stay in metadata and declare missing approval information.
Cancelled requests have no scope or person.
Once options have scope once. Always labels do not establish persistence.
The recorder omits the decider and persistent grant scope.
Policy decisions that never cross ACP remain missing.

Prompt acceptance uses the successful response and its message ID.
Echoed prompt messages are deduplicated. The recorder does not guess human authorship.
V1 has no stable message IDs and no separate acceptance boundary.
Its prompt is retained at successful response receipt and its message-ID loss is declared.
No inference records are invented from messages or context-window counts.
Usage updates retain context counts as metadata and cost when supplied.

Use `--selector ID=mode` or `--selector ID=approval` only when the agent documents
what that configuration option means. Categories alone are not enough.
The recorder preserves the observed current value and does not infer asking behavior.
Tools, effective sandbox settings and per-call usage remain missing.

An observed subagent association supplies a child's parent when known before its header.
Late associations stay on the parent's metadata and declare the child-side limit.
Compaction summaries have harness authorship and a following gap.
Unavailable related sessions remain unresolved references.

Resume with the same ID appends to the existing stream.
Stable message and tool identities prevent duplicate core records on replay.
Replayed history has no invented receipt timestamps.
Updates to completed entities remain in metadata and declare the loss.
The proxy does not rewrite completed lines. V1 replay cannot be deduplicated reliably.
Fork replay requires an established parent identity. Copy detection remains incomplete.
There is no multi-process coordination. Resume is bounded by the writer's 8 MiB limit.
Capture frames are bounded at 16 MiB. Larger wire frames still reach the peer unchanged.
Capture stops after 64 MiB of observed JSON, 100,000 observations or 128 sessions.
Storage and capture failures disable recording and preserve the agent's exit code.
The recorder adds a gap and a loss when storage still accepts writes.
Offline replay fails on oversized input. See [the threat model](../../SECURITY.md).

## Checks

```sh
uv run --all-packages pytest recorders/acp/tests
uv run asr-acp --output /private/fixture-run --agent com.example.agent \
  --traffic recorders/acp/tests/fixtures/v2.traffic.jsonl
node tools/validator/bin/asr-validate.js /private/fixture-run
```

The tests check permission choices, source order, effective input, edits, settings,
replay, incomplete history, privacy and exact large native values.
Every produced stream is checked by the reference validator.

## Test status

Live-test status: **partial**.
The current recorder passes offline regression checks. A live run of this
revision is pending.

New and forked sessions can record cwd and Git metadata observed in their local
working directory. Missing Git leaves cwd available. Loading or resuming an
existing session does not establish its original cwd, branch or HEAD. A remote
path that cannot be read locally supplies no repository facts. Reasoning keeps
its recorded text without claiming full visibility. Empty thinking is omitted.
