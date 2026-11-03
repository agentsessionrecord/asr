---
title: "Agents"
description: "Agent short names and a template for converter notes."
---

The agent list assigns short names for `agent.name`. It is maintained by pull request. An unlisted agent uses a reverse-DNS name under a domain its maintainer controls.

An entry identifies an agent. It does not claim that a converter exists or that every release is supported. The same list is available as [JSON](https://agentsessionrecord.org/agents/agents.json).

## Start here

Start with a converter note below. The other rows reserve a short name only.

- [Claude Code](claude-code.md)
- [Codex](codex.md)
- [Gemini CLI](gemini-cli.md)
- [OpenCode](opencode.md)
- [OpenClaw](openclaw.md)

## Agent list

| Agent | Short name | Homepage | Converter notes |
|---|---|---|---|
| Amp | `amp` | [ampcode.com](https://ampcode.com/) | No |
| Antigravity | `antigravity` | [antigravity.google](https://antigravity.google/) | No |
| AstrBot | `astrbot` | [astrbot.app](https://astrbot.app/) | No |
| Auggie | `auggie` | [www.augmentcode.com](https://www.augmentcode.com/) | No |
| [Claude Code](claude-code.md) | `claude-code` | [code.claude.com](https://code.claude.com/) | [Yes](claude-code.md) |
| Cline | `cline` | [cline.bot](https://cline.bot/) | No |
| CodeBuddy | `codebuddy` | [www.codebuddy.cn](https://www.codebuddy.cn/) | No |
| [Codex](codex.md) | `codex` | [openai.com/codex](https://openai.com/codex/) | [Yes](codex.md) |
| Continue | `continue` | [www.continue.dev](https://www.continue.dev/) | No |
| Copilot CLI | `copilot-cli` | [github.com/github/copilot-cli](https://github.com/github/copilot-cli) | No |
| Crush | `crush` | [github.com/charmbracelet/crush](https://github.com/charmbracelet/crush) | No |
| Cursor | `cursor` | [cursor.com](https://cursor.com/) | No |
| Deep Agents | `deepagents` | [github.com/langchain-ai/deepagents](https://github.com/langchain-ai/deepagents) | No |
| DeepSeek Harness | `deepseek-harness` | [www.deepseek.com](https://www.deepseek.com/) | No |
| Devin | `devin` | [devin.ai](https://devin.ai/) | No |
| Droid | `droid` | [factory.ai](https://factory.ai/) | No |
| Firebender | `firebender` | [firebender.com](https://firebender.com/) | No |
| ForgeCode | `forgecode` | [forgecode.dev](https://forgecode.dev/) | No |
| fx | `fx` | [fx.sh](https://fx.sh/) | No |
| [Gemini CLI](gemini-cli.md) | `gemini-cli` | [geminicli.com](https://geminicli.com/) | [Yes](gemini-cli.md) |
| Goose | `goose` | [aaif-goose.github.io/goose](https://aaif-goose.github.io/goose/) | No |
| Grok Build | `grok-build` | [grok.com](https://grok.com/) | No |
| Hermes Agent | `hermes` | [hermes-agent.nousresearch.com](https://hermes-agent.nousresearch.com/) | No |
| Junie | `junie` | [www.jetbrains.com/junie](https://www.jetbrains.com/junie/) | No |
| Kilo | `kilo` | [kilo.ai](https://kilo.ai/) | No |
| Kimi Code | `kimi-code` | [www.kimi.com/code](https://www.kimi.com/code) | No |
| Kiro | `kiro` | [kiro.dev](https://kiro.dev/) | No |
| Qoder CN | `lingma` | [qoder.cn](https://qoder.cn/) | No |
| MiMoCode | `mimocode` | [mimo.xiaomi.com](https://mimo.xiaomi.com/) | No |
| Mistral Vibe | `mistral-vibe` | [github.com/mistralai/mistral-vibe](https://github.com/mistralai/mistral-vibe) | No |
| Mux (legacy) | `mux` | [mux.coder.com](https://mux.coder.com/) | No |
| NanoClaw | `nanoclaw` | [nanoclaw.dev](https://nanoclaw.dev/) | No |
| [OpenClaw](openclaw.md) | `openclaw` | [openclaw.ai](https://openclaw.ai/) | [Yes](openclaw.md) |
| [OpenCode](opencode.md) | `opencode` | [opencode.ai](https://opencode.ai/) | [Yes](opencode.md) |
| OpenHands | `openhands` | [openhands.dev](https://openhands.dev/) | No |
| Pi | `pi` | [pi.dev](https://pi.dev/) | No |
| Qoder | `qoder` | [qoder.com](https://qoder.com/) | No |
| Qwen Code | `qwen-code` | [github.com/QwenLM/qwen-code](https://github.com/QwenLM/qwen-code) | No |
| Roo Code | `roo-code` | [roocode.com](https://roocode.com/) | No |
| Rovo Dev | `rovodev` | [www.atlassian.com/software/rovo-dev](https://www.atlassian.com/software/rovo-dev) | No |
| Shelley | `shelley` | [exe.dev](https://exe.dev/) | No |
| T3 Code | `t3-code` | [t3.codes](https://t3.codes/) | No |
| Tabnine | `tabnine` | [www.tabnine.com](https://www.tabnine.com/) | No |
| Warp | `warp` | [www.warp.dev](https://www.warp.dev/) | No |
| Xum | `xum` | [xum.coder.com](https://xum.coder.com/) | No |
| Zed | `zed` | [zed.dev](https://zed.dev/) | No |

## Converter notes template

Converter notes add no requirements. Use the following headings in order and keep each mapping concise. Name the native fields and the source versions that support each mapping. If a fact is not documented, say so. Related undocumented fields can share one "Unmapped evidence" paragraph in place of repeated sections. Mark partial notes clearly.

1. **Logs and format.** Where the logs live, their storage shape and the string used for `producer.source`.
2. **Session identity.** The native `sessionId` and whether `namespace` is needed.
3. **User and settings.** Native sources for `user`, call or turn model settings, and agent mode, approval and sandbox policies. Identify undocumented fields and settings that need `_meta`.
4. **Record and call IDs.** Sources of record `id`, `callId`, `turnId` and `inferenceId`, including deterministic derivations and ambiguous joins.
5. **Subagents and parents.** Native pointers for delegation, forks, continuations and copied records.
6. **File-edit evidence.** Tools and native fields carrying edit text, and their mapping to `patch`, `edits`, `before` or `after`. Explain how application is established.
7. **Commit evidence.** Structured Git results or the command output shape the converter may parse. Keep mentions distinct from performed actions.
8. **Usage arithmetic.** How per-call and session totals are identified, which counts include cache or reasoning, and the source of cost.
9. **Missing data.** What goes in `missing`, which records can be truncated, and where gaps arise.
10. **Capture coverage.** A table covering messages, calls, approval decisions and scopes, agent settings and asking, outer sandboxes, triggers, hooks, store changes and pruning.
11. **Source versions.** The releases or source documents described and the limits of the available samples.
12. **Worked example.** A few native log lines beside the ASR records they produce, with the resulting `missing` list. Label synthetic examples and state which fields establish each mapping.

Native fields without a core home can go in `_meta` under the agent's reverse-DNS key, at the converter's choice. Do not retain known secrets or opaque provider state. For every converter and recorder mapping, publish synthetic native inputs, the ASR they produce and the source versions supported. Recorder inputs can be hook payloads or connection messages. A valid example alone does not establish native behavior.

[Conformance](../spec/conformance.md) defines writer and reader behavior. [Missing data](../spec/missing-data.md) explains how to represent a source's limits.

The `mux` short name remains available for legacy logs. Xum uses `xum`.
Qoder CN keeps `lingma` for compatibility with its recorded logs.
