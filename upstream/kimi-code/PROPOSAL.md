# Kimi Code session export

Export saved Kimi Code sessions as Agent Session Record alongside the existing session import support.

The patch adds a format option to the existing `kimi export` command through the SDK and engine export service. ASR mode writes a ZIP containing only a manifest and `session.asr.jsonl`. The default diagnostic ZIP remains available. The new mode is gated by `KIMI_CODE_EXPERIMENTAL_AGENT_SESSION_EXPORT`.

```sh
KIMI_CODE_EXPERIMENTAL_AGENT_SESSION_EXPORT=1 \
  kimi export SESSION_ID --format agent-session -o record.zip
unzip -p record.zip session.asr.jsonl > session.asr.jsonl
```

The reader uses the main agent's `agents/main/wire.jsonl` journal with protocol 1.5. It preserves physical journal order, including retained abandoned work. It keeps explicit human prompts, harness injections, visible reasoning, encrypted reasoning markers, tool calls, and final results. Unsafe integer arguments are kept as decimal strings. Incomplete tails and malformed lines become gaps. Older wire protocols are rejected. Subagents, relationships, media, provider state, usage, settings, approvals, edits, and commits are declared missing. The export is not a redactor. Review conversation content before sharing.

The patch targets [kimi-code](https://github.com/MoonshotAI/kimi-code) at `444c609e8e6629d43fb7fd571a8db48ce5a41570`. Tests cover exact text, source order, final tool results, and excluded provider state. [TESTS.json](TESTS.json) states which checks ran on this revision.
