# Source evidence and attribution

The converters support the native profiles listed in the adapter guides and
committed fixtures. A role describes model context. It does not identify a person.
The table covers all 44 converter selections. Separate storage profiles can share
an implementation.

`Unknown` means the supported profile supplies no discriminator that establishes
a person's input. The converter leaves human authorship absent. Explicit native
`author` and `origin` fields survive the shared document chat mapping.

| Converter | Person input evidence | Recorded location evidence |
| --- | --- | --- |
| `claude-code` | `origin.kind: human`, with queued and meta overrides | First recorded `cwd`, `gitBranch` |
| `codex` | `content_item_kinds` values `user.text` and `user.image` | `session_meta.cwd` and `git` |
| `astrbot` | Unknown in retained conversation messages | Session metadata when supplied |
| `crush` | Unknown in role-tagged parts | Session metadata when supplied |
| `lingma` | Unknown in prompt and answer summaries | Session metadata when supplied |
| `shelley` | Unknown in stored LLM messages | Conversation `cwd` when supplied |
| `deepagents` | Unknown in LangGraph human messages | No established location in the supported root writes |
| `forgecode` | Unknown in context message entries | Conversation metadata when supplied |
| `opencode` | Unknown in stored user rows | Session `directory`, recorded Git metadata when supplied |
| `kilo` | Same supported contract as OpenCode | Same supported contract as OpenCode |
| `mimocode` | Same supported contract as OpenCode | Same supported contract as OpenCode |
| `zed` | Unknown in `User` message variants | `initial_project_snapshot.worktree_snapshots[].git_state` and `worktree_path` |
| `devin` | Native human node discriminator | Session `working_directory` |
| `firebender` | Unknown in saved messages | Session metadata when supplied |
| `goose` | Unknown for both ordinary input and steer messages | Session `working_dir` |
| `kiro` | `Prompt.prompt` and `CancelledToolUses.prompt`, at part level | Recorded directory key or body metadata |
| `warp` | Unknown in supported protobuf variants | Conversation metadata when supplied |
| `cursor` | Unknown in agent transcript role | Recorded session metadata when supplied |
| `gemini-cli` | Unknown in saved `user` messages | Recording metadata when supplied |
| `mistral-vibe` | Unknown in saved user role | Legacy `origin_directory` or `environment.working_directory`, `git_branch`, `git_commit`. Unified `session_metadata` |
| `mux` | Unknown in chat messages | Recorded `metadata.projectPath`, no inferred Git branch from its name |
| `xum` | Unknown in chat messages | Recorded `metadata.projectPath`, no inferred Git branch from its name |
| `fx` | Unknown in turn snapshots | `session_started.payload.workspace_root` |
| `antigravity` | Unknown in rendered transcript entries | Recorded header metadata when supplied |
| `tabnine` | Unknown in saved messages | Recorded header metadata when supplied |
| `qoder` | Unknown in journal user role | Header `cwd` |
| `droid` | Unknown in journal user role | Session start `cwd` |
| `copilot-cli` | Unknown in ordinary user events. Scheduled and generated sources retain their provenance | `session.start.data.context.cwd` |
| `qwen-code` | `provenance: real_user` | Recorded journal `cwd` |
| `grok-build` | Unknown in ACP message updates | Recorded session metadata when supplied |
| `pi` | Unknown in user message role | Session header `cwd` |
| `kimi-code` | `TurnBegin.user_input.origin.kind: user` | State `workDir` or `cwd` |
| `deepseek-harness` | Message `source.kind: user` | Session header `cwd` |
| `junie` | Unknown in prompt events | Recorded event metadata when supplied |
| `openclaw` | Native human sender. Synthetic, runtime and inter-session provenance takes precedence | Native session `cwd`, explicit repository metadata |
| `auggie` | Unknown in request exchanges | `workspaceRoot` or recorded working directory |
| `cline` | Unknown in API history and SDK messages | Task metadata `cwd` |
| `codebuddy` | Unknown in saved chat roles | Recorded `cwd` |
| `continue` | Unknown in saved history roles | Recorded workspace or working directory metadata |
| `hermes` | Unknown in stored message roles | Session `cwd` |
| `nanoclaw` | Unknown in mailbox rows. A channel does not identify a person | Recorded session metadata when supplied |
| `openhands` | Legacy message action `source: user` | Recorded event/session metadata when supplied |
| `roo-code` | Same supported API history contract as Cline | Task metadata `cwd` |
| `rovodev` | Unknown in Pydantic `user-prompt` parts | Recorded session metadata |

No converter runs Git or reads the current checkout to fill these fields. An
explicit repository list establishes repository paths. Codex Git metadata,
Claude Code's recorded branch, Mistral Vibe's Git fields and Zed's initial Git
snapshot also establish repository entries. A working directory alone does not.
Full commit IDs must have 40 or 64 hexadecimal digits. Remote URLs with embedded
URL credentials, queries or fragments are excluded. A recorded directory can lie
inside a repository. Readers still need to verify its relation to the selected
Git worktree.

Location capture uses explicit metadata fields, including `cwd`, `working_dir`,
`working_directory`, `directory`, `workspaceDirectory`, `workspaceRoot` and
`workspace_root`. It does not extract paths or Git facts from prose, hashes,
filenames or tool arguments. Later directory observations do not replace the
starting directory in the header.

## Why a user role stays unknown

Gemini CLI's `chatRecordingService.ts` exposes `recordSyntheticMessage`, and
`geminiChat.ts` records generated context as a user message. Cline's SDK
`messages-contract-v1.md` puts tool results inside user messages. DeepAgents'
`goal_state_notice.py` and `local_context.py` construct generated `HumanMessage`
objects with `additional_kwargs.lc_source`. Zed's stored `UserMessage` contains
an ID and content without a person discriminator. OpenCode exposes both user
and synthetic input admission APIs. Absence of a synthetic marker does not
establish that a person typed an ordinary API input.

Goose's `MessageMetadata.steer` identifies queued input from any client. It does
not establish a person as the author. Its `turn_context` and compaction markers
take precedence and identify harness input. OpenHands' legacy message action
records the event source separately from the LLM role.

## Edit and reasoning evidence

Claude Code SDK structured tool results are success objects. An explicit
`is_error` value overrides that rule. An interrupted result stays interrupted.
A staged change stays proposed. Text-only results with no outcome evidence stay
unknown. Edit and MultiEdit replacements use the recorded result, or effective
input when a linked result establishes success. Write retains full recorded
before and after strings. `updatedInput` takes precedence over the model's
original arguments. Result metadata retains `structuredPatch` and `userModified`.
SDK-originated input alone does not establish a human author. Served service tier
stays in agent metadata. Request settings keep the linked request's own tier.

Codex patch completion can establish application of a linked `apply_patch`
request. The converter parses the native patch framing into replacement snippets.
It does not promote success text to an execution status. Unsupported framing,
including carriage returns, stays native evidence with a declared file-change
loss. Recorded structured changes take precedence over parsed request text.

Claude Code's Anthropic thinking blocks and native thought summaries use `visibility: summary`.
Empty thinking uses `visibility: omitted` with no content. Opaque reasoning uses
the encrypted form without opaque bytes. Other reasoning text retains an absent
visibility when the source does not establish its representation. No converter
claims full reasoning from a field name alone.

## Recovery and checks

A projected record that fails the ASR schema becomes an unparseable gap. The
header declares `record_shape`, and diagnostics name the recorded session.
An invalid session header or failed projection skips that session. Independent
sessions continue. Source staging uses rollback boundaries. If a source fails
before its identity is available, diagnostics identify its deterministic source
ordinal. Database identity collisions skip the conflicting session rather than
selecting one store's history.

The integration tests compare all five published agent-note worked examples
with their documented core facts and inference links. The other profiles have
native fixtures and exact goldens. The public CLI test converts two authored
successful edits, validates the output, commits each edit in a scratch Git
repository and resolves the changed line with blame. It checks the citation,
prompt, served model and absence of invented commit credit. These are synthetic
offline checks. They do not establish live-agent compatibility.

Rust producers use `redacted_content` for content removed by privacy filtering.
This loss includes removed credentials and secret answers.
