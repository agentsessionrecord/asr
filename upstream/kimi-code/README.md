# Agent Session Record export for Kimi Code

This patch adds an ASR format to the existing `kimi export` command in [Kimi Code](https://github.com/MoonshotAI/kimi-code), through the SDK and engine export service. The new mode is gated by `KIMI_CODE_EXPERIMENTAL_AGENT_SESSION_EXPORT` and writes a ZIP holding only a manifest and `session.asr.jsonl`. The default diagnostic ZIP is unchanged. The pinned base is `444c609e8e6629d43fb7fd571a8db48ce5a41570`. [Apply the patch](../README.md#apply-a-patch) in a clean checkout at that base. Building needs Node 24.15 or newer and pnpm 10.33.

```sh
KIMI_CODE_EXPERIMENTAL_AGENT_SESSION_EXPORT=1 \
  kimi export SESSION_ID --format agent-session -o record.zip
unzip -p record.zip session.asr.jsonl > session.asr.jsonl
```

The reader uses the main agent's `agents/main/wire.jsonl` journal with protocol 1.5 and rejects older wire protocols. It keeps physical journal order, including retained abandoned work, and exports explicit human prompts, harness injections, visible reasoning, encrypted reasoning markers, tool calls and final results. Unsafe integer arguments are kept as decimal strings, and incomplete tails and malformed lines become gaps. Subagents, relationships, media, provider state, usage, settings, approvals, edits and commits are declared missing. The export does no redaction, so review the content before sharing.

## Checks

```sh
node upstream/kimi-code/check.mjs
node upstream/kimi-code/reproduce.mjs /path/to/patched-checkout
node upstream/kimi-code/reproduce-native.mjs /path/to/patched-checkout
```

See [package checks](../README.md#check-a-package). The third command runs the dependency-free native reader to reproduce the sample and needs Node 24.15 or newer. Focused tests cover the engine export service and CLI delegation. Full engine, SDK and CLI checks need the upstream workspace dependencies. [TESTS.json](TESTS.json) records the current scope. No live model run covers this revision.

Kimi Code is the TypeScript kimi-code repository. The older Python kimi-cli repository is archived. Upstream accepts external feature pull requests only by maintainer invitation, so this is a local reference patch.
