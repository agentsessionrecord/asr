---
title: "Agents"
description: "Agent short names and a template for converter notes."
---

Every Agent Session Record (ASR) file names its agent in `agent.name`. The list below assigns short names for that field, and changes to it go through pull requests. An agent that is not listed uses a reverse-DNS name under a domain its maintainer controls. A listed name only identifies the agent. It does not mean a converter exists or that every release is supported. The list is also available as [JSON](https://agentsessionrecord.org/agents/agents.json).

## Converter notes

Five agents have converter notes, which describe how their native logs map to ASR and what each conversion loses:

- [Claude Code](claude-code.md)
- [Codex](codex.md)
- [Gemini CLI](gemini-cli.md)
- [OpenCode](opencode.md)
- [OpenClaw](openclaw.md)

## Shared mappings

These rules hold for all five converter notes unless a page says otherwise.

- Native fields with no ASR field can go in `_meta` under the agent's reverse-DNS key, which each page names. Do not keep known secrets or opaque provider state, including in tool definitions and instructions.
- When the log has no user identity, a separately observed Git identity or a configured exporter identity can supply `user`, with its own `source`.
- Leave a model setting absent unless the log records it for that call or turn. Model names and token counts do not establish settings.
- Derive stable IDs when one native item splits into several records. Matching IDs or similar text never establish parent, fork or copy links.
- When a shell call runs `git commit` and its linked result succeeds, output of the form `[branch short-id] subject` supports a `vcs` record with `evidence: parsed_output`, `commitPrefix` and `subject`. Parent counts need their own evidence.
- List in `missing` any edit, commit, usage or copy mapping the converter does not support.
- Pinned sources and samples establish fields for the versions they describe, not for every release.

The specification covers the rest, including [settings changes](../spec/records.md#session_info), [file changes](../spec/records.md#file_change), [commits](../spec/records.md#vcs), [token totals](../spec/records.md#usage-and-cost) and [native trees and copies](../spec/sessions.md).

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

The `mux` short name stays available for legacy logs, and Xum uses `xum`. Qoder CN keeps `lingma` to match its recorded logs.

## Converter notes template

Converter notes add no requirements to the format. Use these headings in order and keep each mapping short. Name the native fields and the source versions that support each mapping, and say when a fact is not documented. Related undocumented fields can share one "Unmapped evidence" paragraph instead of separate sections. Mark partial notes clearly.

1. **Logs and format.** Log location, storage and the `producer.source` string.
2. **Session identity.** The native `sessionId` and whether `namespace` is needed.
3. **User and settings.** Sources for `user`, call or turn model settings, and agent mode, approval and sandbox policies.
4. **Record and call IDs.** Sources of record `id`, `callId`, `turnId` and `inferenceId`, derived IDs and ambiguous joins.
5. **Subagents and parents.** Native pointers for delegation, forks, continuations and copies.
6. **Tool kinds and file edits.** The map from tool names to `kind`, the fields that carry edit text and their mapping to `patch`, `edits`, `before` or `after`, and what establishes that an edit was applied.
7. **Commits.** Structured Git results, or command output the converter may parse.
8. **Token usage and cost.** Per-call and session totals, which counts include cache or reasoning, and where cost comes from.
9. **Missing data.** What goes in `missing`, what can be truncated and where gaps arise.
10. **Approvals and agent settings.** Decision, decider and scope mappings, how `asks` is derived and whether an outer sandbox is recorded.
11. **Triggers, hooks and storage.** A table of trigger fields, hook effects, store changes and pruning.
12. **Source versions.** The releases or source documents described and the limits of the samples.
13. **Worked example.** A few native lines beside the ASR they produce, with the `missing` list. Label synthetic examples and say which fields establish each mapping.

Sections for other sources, such as live hooks or a native export, go after these.

For every converter and recorder mapping, publish synthetic native inputs, the ASR they produce and the source versions supported. Recorder inputs can be hook payloads or connection messages. A valid example alone does not establish native behavior.

[Conformance](../spec/conformance.md) defines writer and reader behavior, and [Missing data](../spec/missing-data.md) explains how to represent a source's limits.
