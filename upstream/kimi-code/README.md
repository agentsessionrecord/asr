# Kimi Code ASR export

The patch adds a format option to the existing `kimi export` command through the SDK and engine export service. ASR mode writes a ZIP containing only a manifest and `session.asr.jsonl`. The default diagnostic ZIP remains available. The new mode is gated by `KIMI_CODE_EXPERIMENTAL_AGENT_SESSION_EXPORT`.

Source: https://github.com/MoonshotAI/kimi-code. Pinned base: `444c609e8e6629d43fb7fd571a8db48ce5a41570`.

Apply `patches/*.patch` with `git am` in a clean writable checkout at the pinned base. Build the patched source using its own instructions.

```sh
KIMI_CODE_EXPERIMENTAL_AGENT_SESSION_EXPORT=1 \
  kimi export SESSION_ID --format agent-session -o record.zip
unzip -p record.zip session.asr.jsonl > session.asr.jsonl
```

The reader uses the main agent's `agents/main/wire.jsonl` journal with protocol 1.5. It preserves physical journal order, including retained abandoned work. It keeps explicit human prompts, harness injections, visible reasoning, encrypted reasoning markers, tool calls, and final results. Unsafe integer arguments are kept as decimal strings. Incomplete tails and malformed lines become gaps. Older wire protocols are rejected. Subagents, relationships, media, provider state, usage, settings, approvals, edits, and commits are declared missing. The export is not a redactor. Review conversation content before sharing.

Node 24.15 or newer and pnpm 10.33 are required. Focused tests cover the engine export service and CLI delegation. The dependency-free native reader can reproduce the sample with `node upstream/kimi-code/reproduce-native.mjs /path/to/patched-checkout` on Node 24.15 or newer. Full engine, SDK, and CLI checks need the upstream workspace dependencies.

Run these package checks from the ASR repository:

```sh
node upstream/kimi-code/check.mjs
node upstream/kimi-code/reproduce.mjs /path/to/patched-checkout
```

Package reproduction replays the patch in a temporary Git index. It preserves the checkout and does not compile the agent. [TESTS.json](TESTS.json) records the current verification scope. No current model session was run.

The current project is the TypeScript kimi-code repository. The old Python kimi-cli repository is archived. External feature PRs require maintainer invitation. This is a local reference patch. The minor CLI changeset text was approved by the requester.
