---
title: "Git AI"
description: "Write Git AI authorship notes from edits that survive in a commit."
---

This guide connects ASR with the [Git AI Standard](https://github.com/git-ai-project/git-ai/tree/main/specs), version 3.0.0. It adds no requirements. Git AI stores line attribution in Git notes. ASR stores the session behind those lines.

## Establish edited by first

Use the [code links and blame rules](../spec/code.md). Start with the commit's added lines and candidate sessions' original, applied `file_change` records for the same path.

- Before and after states identify lines the edit added. An after-state match alone cannot distinguish this edit from dirty worktree changes.
- A recorded patch can identify added lines that survive in order.
- Replacements contribute only lines added between `oldText` and `newText`, excluding unchanged context, with a unique match among the commit's added lines.

Repeated or ambiguous snippets do not attribute a line. When several changes match and their order is established, use the latest surviving change and show the earlier matches as alternatives. Competing sessions without an established order remain unresolved. Exclude copied records. A recorded human edit credits a person. An external edit with no known actor stays untracked.

A session may have edited the lines even if a person made the commit. Conversely, a session that made the commit may have committed someone else's edits. Commit records, trailers and notes help locate candidates. They do not establish line authorship alone.

For example, the following excerpt supplies replacement text to check against Git:

```jsonl
{"type":"file_change","id":"edit-4","path":"/work/parser/parser.py","op":"modify","status":"applied","callId":"replace-4","edits":[{"oldText":"    return int(value)\n","newText":"    return int(value or \"0\")\n"}]}
```

The reader needs the containing session, the associated call and the repository to resolve the full attribution. It does not credit the whole file from this snippet.

## Write the note

Git AI authorship notes live under `refs/notes/ai`. Its format has file paths and line attestations, a separator line containing `---`, and JSON metadata. Use Git AI's implementation to serialize the ranges and metadata for the target commit.

Populate the session's agent and model information only from recorded facts. The served model comes from the `inference` linked to the causing tool call. If only a requested model is known, keep that distinction in the export or accompanying view. Do not present a configured alias as the served model.

Session entries in Git AI 3.0.0 exclude `messages`, `messages_url` and statistics. Keep prompts and transcripts outside Git notes. An ASR lookup can retrieve the session separately under its own access policy.

## The session join key

Git AI computes its session key as `s_` followed by the first 14 lowercase hexadecimal digits of SHA-256 over the UTF-8 bytes of `<tool>:<conversation_id>`.

Here, `tool` is Git AI's tool name and `conversation_id` is ASR's native `sessionId`, verbatim. Do not hash the percent-encoded ASR reference or replace the native ID with a new one.

ASR short names and Git AI tool names are different identifiers. An exporter needs an explicit mapping checked against the Git AI implementation it targets. This guide does not assign unverified tool names.

Git AI's key has no namespace. If the ASR session needs `namespace`, two installations can yield the same key. A key match is ambiguous until other evidence distinguishes the sessions. Do not discard the namespace from ASR to make the join appear unique.

## Trace keys and repeated exports

Git AI's `t_` trace key is opaque to its readers. For repeatable ASR exports, compute SHA-256 over the UTF-8 bytes of `<sessionRef>#<fileChangeId>`. Take the first 14 lowercase hexadecimal digits of the digest and prefix them with `t_`. Here `sessionRef` has no fragment and `fileChangeId` is percent-encoded using ASR's reference rules. The entire record reference is hashed, including the `#` and record ID.

This key locates the source edit. It does not replace the repository checks or turn a possible match into an attribution.

## Rewrites and publication

Follow recorded `rewrites` pairs when connecting commits across amendments and rebases. Never create pairs from matching subjects or similar patches. For a squash merge, compare the squash commit's added lines against the recorded edits.

Export notes for commits as they exist. Git AI's hooks handle carrying notes through repository operations. Integrating with those hooks avoids competing rewrite behavior.

Writing or publishing notes should be an explicit repository choice. Git does not push notes by default. The [integration guide](integration.md) describes session references and commit trailers.
