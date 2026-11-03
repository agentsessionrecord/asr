---
title: "Agent Session Record: an open format for recorded agent sessions"
description: "The need for a common agent session record, the design of ASR and a call for review."
subtitle: "A white paper and call for review"
version: "v0.1 draft"
date: "October 2026"
authors: "Wills Manley"
repository: "https://agentsessionrecord.org"
---

<!-- titleblock -->
# Agent Session Record: an open format for recorded agent sessions

*A white paper and call for review*

**v0.1 draft** · October 2026<br>
Wills Manley
<!-- /titleblock -->

## Abstract

Agent Session Record (ASR) is an open format for recording what an AI agent did in a session. It stores prompts, replies, tool calls, file edits and commits in JSON Lines. Converters give native agent logs a common shape, so tools can search work across agents and connect a line of code to the session behind it.

The core answers a small set of practical questions. Which session edited this line, from which prompt, with which model? Which session made the commit? What failed, and what happened next? ASR keeps the facts needed to investigate those questions while making missing information visible. It works alongside live agent protocols, Git attribution notes and telemetry. This paper describes the format, its use for blame, and the path from native logs to useful readers.

## 1. The gap between protocols, notes and telemetry

An agent can finish a change in minutes. The code may need explanation months later. Git retains the file history, but the commit message rarely includes the complete request, the rejected approach or the test output that shaped the result. Those facts live in an agent's session storage, if they remain available at all.

Each agent chooses a storage format for its own needs. Some append events to JSONL. Others update a document or store messages and parts in a database. A reader must understand how the source identifies sessions, joins tool calls to results and records changes. That work repeats for every search engine, code review tool and session viewer.

Several useful standards cover adjacent parts of the problem. The Agent Client Protocol (ACP) connects an editor or another client to a running agent [[1](#ref-1)]. The Model Context Protocol (MCP) supplies common shapes for tool interactions and content [[2](#ref-2)]. These protocols help software cooperate during execution. A live connection does not by itself define the durable record available afterward. Most agent sessions run without an ACP connection, so there is often nothing live to record. Converters cover them from native logs.

Git AI records line attribution in Git notes [[3](#ref-3)]. A note can connect a line to an agent session without putting the transcript into repository history. It does not replace the session's account of the request, model call, edit and result. OpenTelemetry's GenAI conventions describe model and tool operations for monitoring [[4](#ref-4)]. Their spans answer timing and usage questions, while capture and sampling choices affect which content is retained.

ASR occupies the record layer alongside these tools. It reuses familiar content shapes, can supply the session behind a Git AI attribution, and can export recorded operations to OpenTelemetry. A common file format gives each integration one shape to read without making every agent change its native storage.

The boundary matters for adoption. A converter can serve an existing log format. A reader can accept its output without understanding that agent's database or release history. The converter remains responsible for explaining the source's limits, and the reader remains responsible for checking repository facts before presenting blame.

## 2. The questions a record should answer

The first question is about a line of code. A reviewer needs to find the session that edited it, the prompt connected to that work, and the model behind the causing tool call. The answer can reveal the intended behavior, the available constraints and the checks performed at the time.

The next questions widen the search. Which sessions made a commit or pull request, and what else did they do? Which sessions read or changed a file? A reader can index tool locations, file changes and version control actions to find those sessions without relying on a filename appearing in prose.

Full-text search also matters. Prompts, replies and tool input and output contain details that structured fields cannot anticipate. An error message can lead to an earlier failed attempt. A phrase from a requirement can lead to the session that implemented it. The same query should work across agents.

Once a session is found, file order provides the sequence of recorded work. A failed tool and the next action can explain how the agent responded. Timestamps help when present, but sorting by them can scramble a source that records delayed events or copied history. A reader uses the order the source retained.

Usage and cost support a different view of the same work. Per-call figures can be grouped by model, while session totals can be shown as the source reports them. The distinction prevents a total from being added to the calls it already includes. Unknown cost stays unknown rather than appearing as a free call.

Delegation introduces another question. Which session started a subagent, with what task, and what came back? Parent pointers and tool links can connect the files without requiring them to be stored together. Copied context is distinguishable from work the child performed itself.

Later outcomes complete the picture. A change may be kept, reverted, merged or abandoned after the session ends. Those facts belong in annotations that can be joined to the session. The original record remains an account of what happened during the work, while later services can add what they learn.

These questions bound the core. A field earns its place by helping answer them at a low cost to a converter or agent. Additional details can remain vendor data or belong to an extension. A reader should not need a complete model of an agent's runtime to search its work.

## 3. The format in brief

An ASR session is a UTF-8 JSON Lines file. Each line contains one completed record and ends with a newline. The first line is the sole `session` record. It identifies format version `0.1`, the agent, its native session ID and the producer that wrote the file. Optional fields describe the user who ran it, working directory, repositories and known missing data. The user is a grouping label, not proof of message or commit authorship.

The core has ten record types. `session_info` adds session facts, totals, settings, offered tools and discovered losses. `message` carries content, including system and developer instructions at their recorded position. `tool_call` and `tool_result` describe activity and outcomes. `approval` records one decision when it happens, even when the call never finishes or the grant has no call. `file_change` records one changed file. `vcs` records version control and pull request actions. `inference` describes one recorded model call, including settings when the source supplies them. `gap` marks missing history.

Settings apply by position. Native approval and sandbox policies retain any recorded JSON value. The optional `asks` summary describes whether policy can require a person before file changes or commands. A policy change without a supplied summary makes it unknown. Configured model settings merge field by field and do not supply absent call settings. A supplied tool list or outer boundary replaces the whole value. The boundary encloses the agent process and its work, rather than selected tools alone.

Every record has a type and a unique ID. Record IDs remain native where possible, or are derived deterministically from source identities or positions. A session reference combines the agent name with its native session ID. An installation namespace is added only when IDs can repeat across installations. A record fragment gives a precise citation within that session.

The following excerpt is a field-identical subset of the [quick tour](https://agentsessionrecord.org/get-started/quick-tour), using a fictional agent fixing an empty-input case. Other records from the session are omitted. The edit is linked to a tool call, and the tool call is linked to the model call that produced it.

```jsonl
{"type":"session","id":"session","formatVersion":"0.1","agent":{"name":"com.example.coder","version":"1.0"},"sessionId":"parser-42","producer":{"name":"example-export","version":"1.0","method":"native"},"cwd":"/work/parser","repos":[{"path":"/work/parser","remote":"https://github.com/example/parser","branch":"fix-empty-limit"}],"missing":["reasoning"]}
{"type":"message","id":"prompt","turnId":"turn-1","role":"user","author":"human","origin":"prompt","content":[{"type":"text","text":"Make an empty limit mean zero. Run the parser tests and commit the fix."}]}
{"type":"inference","id":"model-edit","turnId":"turn-1","model":{"provider":"example","id":"code-model-1"},"usage":{"inputTokens":820,"outputTokens":64}}
{"type":"tool_call","id":"call-edit","turnId":"turn-1","inferenceId":"model-edit","callId":"edit-1","name":"replace_text","kind":"edit","requestedBy":"model","input":{"path":"/work/parser/parser.py","oldText":"    return int(value)\n","newText":"    return int(value or \"0\")\n"},"locations":[{"path":"/work/parser/parser.py"}]}
{"type":"tool_result","id":"result-edit","callId":"edit-1","status":"completed","content":[{"type":"text","text":"Replaced one occurrence in parser.py."}]}
{"type":"file_change","id":"change","path":"/work/parser/parser.py","op":"modify","status":"applied","callId":"edit-1","edits":[{"oldText":"    return int(value)\n","newText":"    return int(value or \"0\")\n"}]}
```

The replacement text supports a check of which added lines survive. The full tour also keeps the short commit ID that Git printed. A reader resolves and checks that ID in the real repository. A statement in a final reply would remain searchable text without establishing either fact.

Paths are plain strings. Producers prefer absolute paths. Relative paths use the session's starting working directory. Paths embedded in tool arguments, commands or patches stay as recorded. Repository paths help the reader select the repository to inspect, but they do not replace verification against Git.

Missing data has explicit meaning. An absent field is unknown. A recorded zero, false value or empty string remains a real value where the field's shape allows it. The header lists known losses, and later `session_info.missing` updates add to that list without removing losses. Shortened text carries `truncated: true`, and gaps locate missing history. A reader reports a malformed line and continues. An unterminated final line is incomplete rather than a finished record.

Live writers append without changing complete lines. Converters may re-export an entire file. Readers interpret file order and preserve unknown data when storing it. Open enums, vendor metadata and namespaced record types allow details to survive tools that do not understand them yet.

## 4. Blame separates editing from committing

Git blame identifies the commit that introduced a line at a path [[5](#ref-5)]. That is the starting point for ASR blame. The session evidence is then checked against repository objects to determine what a session actually did.

Committed by and edited by are different answers. A session can make a commit containing changes from another session or a person. A person can commit an agent's edits. An agent can rebase a branch without writing the lines being rebased. Treating any of those actions as line authorship would conceal the division of work.

A committed-by result requires an original version control record for an action that can produce the commit. Its evidence comes from an observed operation or parsed command output, with `vcs.status` set to `completed`. Only `unknown` falls back to a uniquely paired completed tool result. A stored association, a push, a checkout or a commit mentioned in a message cannot establish that result.

A full recorded commit ID can be compared directly. A short ID needs more checks. It must resolve uniquely in the repository, its recorded subject must match and its repository parent count must fit the action, and the commit must be reachable from a local branch or tag. Recorded parent fields are optional, but must match when present. Git provides the object resolution mechanisms [[6](#ref-6)]. A failed check means the reader does not give commit credit.

Edited-by results start from original, applied file changes for the path. The commit adds all lines for a root commit, or the diff from its first parent otherwise. Before and after states limit credit to lines the edit added. A final blob match alone cannot distinguish an edit from dirty worktree changes. A recorded patch supplies added lines. Text replacements contribute only additions between old and new text, excluding unchanged context.

Repeated snippets and ambiguous matches leave lines unattributed. When several recorded changes survive at the same line, the latest surviving change wins when its order is established. Earlier matches remain visible as alternatives. Competing sessions with no established order remain unresolved. A known human edit credits a person. An observed external edit with no known actor stays untracked. A match is evidence rather than proof of authorship.

Commit rewrites require another join. Recorded old-to-new pairs connect amendments, rebases and cherry-picks to commits that existed during sessions. The reader follows those pairs back from the blamed commit. It checks both objects, carries verified commit history forward and rechecks surviving edits, including pairs supplied by annotations. It does not infer a rewrite from similar patches or subjects. A session that performs the rewrite does not become the editor of the rewritten lines.

Pull requests can connect work across those operations. Recorded member commits or a merge commit supply repository candidates. A later forge annotation can add a merge result. For a single-parent squash or rebase merge, the landed commit is the merge commit itself. The reader compares its added lines directly with recorded edits. The absence of a one-to-one commit rewrite does not prevent a surviving edit from being found.

An attribution view links the edit to its causing call and model call, when available. The served model is shown when recorded. A configured alias remains labeled as the requested model. The associated prompt gives context, while authorship markers distinguish a person's request from injected instructions or a compaction summary.

Git AI notes can be written from these edited-by results. The note carries line attribution, and its session join key helps locate the ASR record. Its tool names and lack of an installation namespace need careful handling when joining sessions. A note is a useful candidate source, but its presence does not replace the underlying checks.

## 5. How sessions get in

Converters are the first path into ASR. They read native files after the work and write completed records. This path needs no agent vendor to adopt a protocol or change its runtime. It also makes existing sessions useful immediately, within the limits of the data still retained.

A converter's job is specific. It identifies the native session, keeps source order, joins calls through documented IDs and copies recorded text. It maps edit and commit evidence only where the source establishes those facts. It does not fill missing timestamps from file modification times or invent model calls from message boundaries.

Converter notes make that work reviewable. They name storage locations and format names, identity rules, edit evidence, usage arithmetic and supported source versions. A native sample lets a reviewer inspect the mapping. If a source description lacks the field needed for a join, the notes say so. Structural validation alone cannot establish that an export faithfully represents the native file.

Agent-provided export is the next path. A stable export command can hide changes in internal storage and supply facts that a separate converter cannot safely recover. An agent can also write ASR beside its native log, retaining internal state in its own format while publishing the facts useful to outside readers.

Recording an ACP connection is another path. It captures what the client and agent exchange, including messages and tools. The recorder folds streaming updates into completed records. It can miss model-call boundaries, source event times or the form of tool output shown to the model. Those limits stay visible in the resulting file.

A useful reader is as important as a writer. If a tool can search many agents and connect results to code, a new converter immediately makes another source available to that tool. Without such readers, a format can be technically implementable while offering little reason to export it.

SARIF provides a useful example of this relationship. The standard defines a common representation for static analysis results [[7](#ref-7)]. GitHub code scanning accepts supported SARIF files from analysis tools [[8](#ref-8)]. A substantial consumer gives producers a concrete benefit from writing the format. ASR seeks the same practical relationship between converters and tools that search and explain code.

A converter that supports search over messages and tool activity for one well-documented agent should take about a day. Blame support depends on documented edit and commit payloads. Undocumented payloads need native samples before a converter can map them. Review seeks evidence of conversion coverage across agent versions and blame results on real repositories, including ambiguous and unknown answers. No coverage or attribution rate is claimed here.

## 6. What ASR does not provide

ASR does not reconstruct the exact request a model saw. Native systems can inject instructions, prune context or retain provider state that a session export does not contain. A sequence of messages and calls can explain recorded work without serving as an exact model input.

It does not define replay or resume. Those operations depend on an agent's execution state and native contracts. Encrypted reasoning and opaque provider state are not a portable substitute. ASR records a reasoning summary or an indication that reasoning is unavailable without retaining opaque provider bytes.

It also does not replace telemetry. A model call can have usage without usable timing. An exporter emits a span only when recorded endpoints or a documented start and duration support it. Session totals remain distinct from per-call totals. Exported monitoring data reflects those limits.

The format does not put transcripts in Git. Commit trailers and attribution notes can refer to sessions, while the session files stay in storage with appropriate access controls. A URL is a locator that may expire or require authentication. It is not the session's identity.

Finally, validity does not establish completeness or safety to share. Prompts, tool definitions and tool output are untrusted content and can contain private information. Producers exclude known secrets. Readers never run commands or fetch URIs found in a stream. Redaction produces a new file whose producer identifies the redactor. An optional digest links its exact source bytes, and known losses remain visible to its readers.

## 7. Extensions, annotations and review

The core can stay small while additional detail remains available. Vendor fields live in `_meta` under reverse-DNS keys. Vendor record types have namespaced names. Storage tools preserve them, and readers ignore meanings they do not understand. Named extensions can add records and fields without changing what core records mean.

Annotations handle facts learned after the session. A separate `.annotations.jsonl` file can record a summary, a test result, a title or an outcome. Each line identifies its target session, the time the fact was learned, its source and its payload. A correcting annotation can name the earlier annotation it supersedes.

Readers join annotations by session reference and apply corrections first. The latest remaining time selects a current summary, outcome or title. Independent test and VCS facts all remain available. An annotation can supply a pull request's merge commit or recorded rewrite pairs. It cannot establish blame by itself. Keeping these facts separate allows a test service, forge sync or person to update the view without editing the historical stream.

The governance rule follows the target questions. A feature belongs in the core when it helps answer them and is cheap for a converter or agent to produce. Proposals need both useful reader behavior and source data that can support it. Guides and converter notes can be corrected independently of the core format version.

Review is most useful when it follows one real piece of work. A sample can show a failed call, a person's commit of an agent edit, copied context or a squash merge. The review asks whether the file preserves the available facts and whether a reader reaches a warranted answer. Cases that remain unknown are as useful as cases that match.

The specification, guides and examples are published for that review [[9](#ref-9)]. Implementations can begin with search and add blame where the source and repository support it. The result is a shared record of agent work that stays useful across changes in agents, models and storage.

## Disclosure

The author also builds [ctx](https://github.com/ctxrs/ctx), an open-source converter and search tool for agent sessions.

## References

1. <a id="ref-1"></a>Agent Client Protocol. *Schema v2.0.0-alpha.9*, wire protocol version 2. <https://github.com/agentclientprotocol/agent-client-protocol/releases/tag/schema-v2.0.0-alpha.9>
2. <a id="ref-2"></a>Model Context Protocol. *Tools and content types.* <https://modelcontextprotocol.io/specification/2026-07-28/server/tools>
3. <a id="ref-3"></a>Git AI. *Git AI Standard*, version 3.0.0. <https://github.com/git-ai-project/git-ai/tree/main/specs>
4. <a id="ref-4"></a>OpenTelemetry. *Semantic conventions for generative AI.* <https://opentelemetry.io/docs/specs/semconv/gen-ai/>
5. <a id="ref-5"></a>Git. *git-blame documentation.* <https://git-scm.com/docs/git-blame>
6. <a id="ref-6"></a>Git. *git-rev-parse documentation.* <https://git-scm.com/docs/git-rev-parse>
7. <a id="ref-7"></a>OASIS. *Static Analysis Results Interchange Format (SARIF) Version 2.1.0*, OASIS Standard, March 2020. <https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html>
8. <a id="ref-8"></a>GitHub Docs. *SARIF support for code scanning.* <https://docs.github.com/en/code-security/code-scanning/integrating-with-code-scanning/sarif-support-for-code-scanning>
9. <a id="ref-9"></a>Agent Session Record. *Specification, format 0.1 draft.* <https://agentsessionrecord.org/spec/overview>
