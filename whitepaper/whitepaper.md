---
title: "Agent Session Record: an open format for recorded agent sessions"
description: "The need for a common agent session record and the design of ASR."
subtitle: "A white paper"
version: "v0.1"
date: "October 2026"
authors: "Wills Manley"
repository: "https://agentsessionrecord.org"
---

<!-- titleblock -->
# Agent Session Record: an open format for recorded agent sessions

*A white paper*

**v0.1** · October 2026<br>
Wills Manley
<!-- /titleblock -->

## Abstract

Agent Session Record (ASR) is an open file format for coding agent sessions. Each session is a JSON Lines file of prompts, replies, tool calls, file edits and commits. Converters turn each agent's native logs into ASR, so one tool can search sessions from many agents and trace a line of code back to the session that produced it.

The format is built around a few questions. Which session edited this line, from which prompt, with which model? Which session made the commit? What failed, and what happened next? ASR keeps the facts needed to answer them and makes missing information explicit.

## 1. Agent logs and related standards

Code an agent wrote in minutes may need explaining months later. Git keeps the file history, but a commit message rarely includes the request, the rejected approach or the test output behind the change. Those live in the agent's session logs, if they survive at all.

Each agent stores sessions its own way, as appended JSONL, an updated document or rows in a database. A tool that reads them has to learn how each agent identifies sessions, joins tool calls to results and records changes, and every search engine, review tool and session viewer repeats that work.

Nearby standards cover other parts of the problem. The Agent Client Protocol (ACP) connects an editor or other client to a running agent [[1](#ref-1)], and the Model Context Protocol (MCP) defines shapes for tool interactions and content [[2](#ref-2)]. Both help software cooperate while an agent runs, but a live connection doesn't define what is kept afterward, and most sessions run without ACP at all. Git AI records line attribution in Git notes [[3](#ref-3)], without the request, model call, edit and result behind the line. OpenTelemetry's GenAI conventions describe model and tool operations for monitoring [[4](#ref-4)], and capture and sampling choices decide how much content is kept.

ASR is the session record alongside these. It reuses MCP content and ACP tool shapes, can supply the session behind a Git AI attribution, and can export recorded operations to OpenTelemetry. Agents keep their native storage. A converter for each log format states that format's limits, and readers can use its output without understanding the agent's database or release history.

## 2. The questions ASR answers

The first question is about a line of code: which session edited it, from which prompt, and with which model. The answer can show the intended behavior, the constraints the agent had and the checks it ran. Related questions widen the search to the sessions that made a commit or pull request, or that read or changed a file. Indexed tool locations, file changes and version control actions answer these without relying on a file name appearing in prose, and full-text search over prompts, replies and tool output covers the rest.

Within a session, file order gives the sequence of work. Sorting by timestamps can scramble a source that records delayed events or copied history. Per-call usage can be grouped by model, while session totals stay separate so they aren't added to the calls they already include. Parent pointers connect a subagent to the session that started it, and outcomes learned later, such as a revert or a merge, go in annotations joined to the session.

A field belongs in the core when it helps answer these questions and is cheap for a converter or agent to produce. Other details can stay in vendor data or an extension.

## 3. The format

An ASR session is a UTF-8 JSON Lines file with one completed record per line. The first line is the only `session` record. It gives format version `0.1`, the agent, its native session ID and the producer that wrote the file, and can add the user who ran it, the working directory, repositories and known missing data. The user is a grouping label, not proof of who wrote a message or made a commit.

The core has ten record types. `session_info` adds totals, settings, offered tools and losses found later. `message` carries content, including system and developer instructions at their recorded position. `tool_call` and `tool_result` describe tool activity and outcomes. `approval` records one decision when it happens, even when the call never finishes or the grant has no call. `file_change` records one changed file, and `vcs` records version control and pull request actions. `inference` describes one recorded model call, and `gap` marks missing history.

Settings apply from their position in the file. Native approval and sandbox policies are kept verbatim. An optional `asks` summary says whether the policy can require a person before file changes or commands, and becomes unknown when the policy changes without a new summary. Configured model settings never fill in settings a call didn't record.

Every record has a type and a unique ID, kept from the source where possible or derived deterministically. A session reference combines the agent name with the native session ID, and a fragment cites one record within it.

The excerpt below comes unchanged from the [quick tour](https://agentsessionrecord.org/get-started/quick-tour), in which a fictional agent fixes an empty-input case. The edit links to a tool call, and the tool call links to the model call that produced it.

```jsonl
{"type":"session","id":"session","formatVersion":"0.1","agent":{"name":"com.example.coder","version":"1.0"},"sessionId":"parser-42","producer":{"name":"example-export","version":"1.0","method":"native"},"cwd":"/work/parser","repos":[{"path":"/work/parser","remote":"https://github.com/example/parser","branch":"fix-empty-limit"}],"missing":["reasoning"]}
{"type":"message","id":"prompt","turnId":"turn-1","role":"user","author":"human","origin":"prompt","content":[{"type":"text","text":"Make an empty limit mean zero. Run the parser tests and commit the fix."}]}
{"type":"inference","id":"model-edit","turnId":"turn-1","model":{"provider":"example","id":"code-model-1"},"usage":{"inputTokens":820,"outputTokens":64}}
{"type":"tool_call","id":"call-edit","turnId":"turn-1","inferenceId":"model-edit","callId":"edit-1","name":"replace_text","kind":"edit","requestedBy":"model","input":{"path":"/work/parser/parser.py","oldText":"    return int(value)\n","newText":"    return int(value or \"0\")\n"},"locations":[{"path":"/work/parser/parser.py"}]}
{"type":"tool_result","id":"result-edit","callId":"edit-1","status":"completed","content":[{"type":"text","text":"Replaced one occurrence in parser.py."}]}
{"type":"file_change","id":"change","path":"/work/parser/parser.py","op":"modify","status":"applied","callId":"edit-1","edits":[{"oldText":"    return int(value)\n","newText":"    return int(value or \"0\")\n"}]}
```

The replacement text lets a reader check which added lines survive in a commit. The full tour also keeps the short commit ID Git printed, which a reader resolves in the real repository. A claim in the final reply stays searchable text and establishes neither fact.

Paths are plain strings, preferably absolute, and relative paths resolve against the starting working directory. An absent field means unknown, while a recorded zero, false or empty string is a real value. The header lists known losses, later `session_info.missing` updates can only add to them, and shortened text carries `truncated: true`. A reader reports a malformed line and continues, and treats an unterminated final line as incomplete.

Live writers append and never change complete lines, while converters may re-export a whole file. Open enums, vendor metadata and namespaced record types let details pass through tools that don't understand them.

## 4. Blame

Git blame identifies the commit that introduced a line at a path [[5](#ref-5)]. ASR blame starts there, checks session evidence against the repository's objects and gives two separate answers, edited by and committed by. A session can commit another session's or a person's changes, a person can commit an agent's edits, and an agent can rebase a branch without writing any of its lines. Treating any of these as authorship would hide who did the work.

Commit credit needs an original version control record for an action that can produce the commit, with `vcs.status` set to `completed` and evidence from an observed operation or parsed command output. Only when the status is `unknown` can a uniquely paired completed tool result establish success. A push, a checkout, a stored association or a commit mentioned in a message doesn't count.

A full recorded commit ID can be compared directly. A short ID must resolve uniquely in the repository, its recorded subject must match, the repository's parent count must fit the action, and the commit must be reachable from a local branch or tag. Recorded parent fields are optional but must match when present. Git provides the object lookup [[6](#ref-6)]. If any check fails, the reader gives no commit credit.

Edit credit starts from original, applied file changes for the path. The commit's added lines are all lines of a root commit, otherwise its diff from the first parent. Before and after states limit credit to lines the edit added, because a matching final file can't tell an edit apart from uncommitted changes already in the worktree. A recorded patch supplies added lines directly, and a text replacement contributes only what it adds, not unchanged context.

Repeated snippets and ambiguous matches leave lines unattributed. When several recorded changes survive at the same line, the latest wins if its order is established, and earlier matches stay visible as alternatives. Competing sessions with no established order stay unresolved. A known human edit credits a person, and an external edit with no known actor stays untracked. A match is evidence, not proof.

Rewritten commits need one more join. Recorded old-to-new pairs, from sessions or annotations, connect amends, rebases and cherry-picks back to commits that existed during sessions. The reader checks both objects, carries verified commit credit forward and rechecks surviving edits. It never infers a rewrite from similar patches or subjects, and performing a rewrite doesn't make a session the editor of the rewritten lines.

Pull requests add candidates through recorded member commits or a merge commit, which a later forge annotation can also supply. For a single-parent squash or rebase merge, the landed commit is the merge commit itself, and the reader compares its added lines directly with recorded edits.

An attribution view links the edit to its tool call, model call and prompt. It shows the served model when recorded, labels a configured alias as the requested model, and uses authorship markers to separate a person's request from injected instructions or a compaction summary. Git AI notes can be written from these edited-by results. In the other direction, a note's session key helps find the ASR file, but the note is a candidate to check, not a substitute for the checks.

## 5. How sessions get in

Converters come first. They read native files after the work, so no agent vendor has to adopt a protocol or change its runtime, and existing sessions become useful right away within the limits of what the logs still hold. A converter keeps source order, joins calls through documented IDs and copies recorded text. It maps edits and commits only where the source establishes them, and doesn't fill missing timestamps from file modification times or invent model calls from message boundaries.

Converter notes make the mapping reviewable. They give storage locations, identity rules, edit evidence, usage arithmetic and supported source versions, with a native sample, because structural validation alone can't show that an export matches the native file.

An agent can also export ASR itself, through a stable export command that hides changes to its internal storage or by writing ASR next to its native log. Either way it can supply facts a converter can't safely recover. Recording an ACP connection is a third path. The recorder folds streaming updates into completed records and can miss model-call boundaries, event times or the exact tool output the model saw, so those limits stay visible in the file.

Producers also need a reason to write the format, and useful readers provide it. SARIF defines a common format for static analysis results [[7](#ref-7)], and GitHub code scanning accepts SARIF files from analysis tools [[8](#ref-8)], and that consumer gives analysis tools a concrete reason to write SARIF. ASR needs the same relationship, where each new converter makes another agent's sessions available to every tool that searches and explains code.

A converter that supports search over messages and tool activity for one well-documented agent should take about a day. Blame needs documented edit and commit payloads, or native samples where they aren't documented.

## 6. Limits

ASR doesn't reconstruct the exact request a model saw, since agents can inject instructions, prune context or keep provider state that an export doesn't contain. It doesn't define replay or resume, which depend on an agent's execution state. It records a reasoning summary, or notes that reasoning is unavailable, and doesn't keep encrypted reasoning or opaque provider bytes.

It doesn't replace telemetry. A model call can have usage without usable timing, so an exporter emits a span only when recorded endpoints or a documented start and duration support it.

It doesn't put transcripts in Git. Commit trailers and attribution notes point to sessions, and the files stay in storage with suitable access controls. A URL is a locator that may expire or need authentication, not the session's identity.

A valid file isn't necessarily complete or safe to share. Prompts, tool definitions and tool output are untrusted and can contain private information. Producers exclude known secrets, and readers never run commands or fetch URIs found in a session. Redaction produces a new file that names the redactor as its producer, with an optional digest of the source bytes.

## 7. Extensions and annotations

Vendor fields go in `_meta` under reverse-DNS keys, and vendor record types have namespaced names. Storage tools keep them and readers ignore meanings they don't understand. Named extensions can add records and fields without changing what core records mean.

Facts learned after a session, such as a summary, test result, title or outcome, go in a separate `.annotations.jsonl` file. Each line names its target session, when the fact was learned and its source. Readers apply corrections first, take the latest remaining summary, outcome or title, and keep all remaining test and VCS facts. An annotation can supply a merge commit or rewrite pairs but can't establish blame by itself. A test service, forge sync or person can add facts without editing the session file.

The specification, guides and examples are published at agentsessionrecord.org [[9](#ref-9)]. An implementation can start with search and add blame where the source and repository support it.

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
9. <a id="ref-9"></a>Agent Session Record. *Specification, format 0.1.* <https://agentsessionrecord.org/spec/overview>
