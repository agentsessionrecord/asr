# Source contracts

The implementation uses structural TypeScript boundaries. It does not bundle
an agent SDK or the agent's Effect runtime. Each entry exports only one plugin.

| Source | Revision | Files reviewed |
| --- | --- | --- |
| [OpenCode](https://github.com/anomalyco/opencode) | `bf5d12c` | `packages/plugin/src/promise/{plugin,tool,permission,session,event,registration}.ts`, `packages/schema/src/{session-event,permission,tool,event}.ts` |
| [Kilo](https://github.com/Kilo-Org/kilo) | `6f08110` | `packages/plugin/src/index.ts`, `packages/opencode/src/{session/prompt,session/message-v2,permission/next,config/config}.ts` |
| [Kilo Code](https://github.com/Kilo-Org/kilocode) | `0a9faef` | `packages/plugin/src/index.ts`, `packages/opencode/src/{session/prompt,permission/index,config/config}.ts` |
| [MiMoCode](https://github.com/XiaomiMiMo/MiMo-Code) | `7bc7dc3` | `packages/plugin/src/index.ts`, `packages/cli/src/{session/prompt,session/message-v2,permission/index,config/config}.ts` |

OpenCode's V2 source has `execute.before` and `execute.after` on `tool.hook`.
Call identity is `id`. Its event envelopes use `data` and its terminal tool
events are `session.tool.success` and `session.tool.failed`. The V2 entry uses
`permission.hook("evaluate", ...)` for observations and `event.subscribe`
for permission replies. Its configuration uses `plugins` rather than `plugin`.
For example, use `{"plugins":["file:///absolute/asr/plugins/opencode/dist/v2.js"]}`.

The released OpenCode 1.19.5 used in the live test accepts named V1 hooks.
The V1 entries implement `tool.execute.before`, `tool.execute.after`,
`permission.ask`, `chat.message`, `event` and optional `dispose`. V1 event
envelopes use `properties`. Terminal tools arrive in `message.part.updated`.
Throws can skip the after hook, so the terminal tool part also handles failure.

The older Kilo active permission path does not invoke `permission.ask`.
MiMoCode declares that hook without an active caller in the reviewed source.
Both expose permission requests and replies through the event callback.
MiMoCode can cancel before execution without invoking the after hook.
Its terminal tool metadata explicitly identifies cancellation.

Permission replies do not carry a reliable person or decider. The older Kilo
`always` grants live in instance memory. MiMoCode can emit the same rejection
event on timeout, and its forced asks can treat an `always` reply as one use.
Kilo Code has extra protected-path and persisted-grant rules. The recorder
preserves the reply without claiming a shared lifetime across these variants.

Lifecycle creation is explicit. No reviewed idle or deletion callback states
that the native session identity has ended. The recorder leaves `endedAt`
absent. Agent selection callbacks are partial settings evidence.

The fixture uses native V1 envelope and field shapes from these sources.
It adds only synthetic identifiers, commands, paths and timestamps. Source
versions and live binary versions are separate claims.
