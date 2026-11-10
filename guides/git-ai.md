---
title: "Git AI"
description: "Write Git AI authorship notes from edits that survive in a commit."
---

The [Git AI Standard](https://github.com/git-ai-project/git-ai/tree/main/specs), version 3.0.0, stores line attribution in Git notes. Agent Session Record (ASR) stores the session behind those lines, so an exporter can write Git AI notes from sessions and a reader can follow a note back to its session.

## Attribute lines from edits

Write notes only from the [edited-by results](../spec/code.md#edited-by), which come from original, applied `file_change` records whose added lines survive among the commit's added lines. A person can commit a session's edits, and a session can commit someone else's. Commit records, trailers and existing notes help find candidate sessions, but none of them attributes a line.

## Write the note

Git AI keeps authorship notes under `refs/notes/ai`. A note holds file paths and line attestations, a separator line containing `---`, and JSON metadata. Use Git AI's own implementation to serialize the ranges and metadata for the target commit.

Fill in the agent and model only from recorded facts. The served model comes from the `inference` linked to the causing tool call. If only the requested model is known, keep it labeled as requested in the export or the view that goes with it, and never present a configured alias as the served model.

Session entries in Git AI 3.0.0 leave out `messages`, `messages_url` and statistics. Keep prompts and transcripts out of Git notes. A reader can fetch the ASR session separately under its own access policy.

## The session join key

Git AI's session key is `s_` followed by the first 14 lowercase hexadecimal digits of SHA-256 over the UTF-8 bytes of `<tool>:<conversation_id>`. Here `tool` is Git AI's tool name and `conversation_id` is the ASR native `sessionId`, verbatim. Don't hash the percent-encoded ASR reference or replace the native ID with a new one.

ASR short names and Git AI tool names are different identifiers. An exporter needs an explicit mapping between them, checked against the Git AI implementation it targets.

Git AI's key has no namespace. If an ASR session needs `namespace`, two installations can produce the same key, and a match stays ambiguous until other evidence tells the sessions apart. Don't drop the namespace from ASR to make the join look unique.

## Trace keys

Git AI's `t_` trace key is opaque to its readers. For repeatable exports, hash the full record reference `<sessionRef>#<fileChangeId>`, including the `#`, as UTF-8 bytes with SHA-256 and prefix the first 14 lowercase hexadecimal digits with `t_`. `sessionRef` has no fragment, and `fileChangeId` is percent-encoded by ASR's reference rules.

The key locates the source edit. It doesn't replace the repository checks or turn a possible match into an attribution.

## Rewrites and publication

Follow recorded `rewrites` pairs to connect commits across amends and rebases, and never build pairs from matching subjects or similar patches. For a squash merge, compare the squash commit's added lines with the recorded edits.

Export notes for commits as they exist. Git AI's hooks carry notes through repository operations, so integrate with those hooks rather than adding competing rewrite behavior.

Write or publish notes only when the repository has chosen to. Git doesn't push notes by default.
