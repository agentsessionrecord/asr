---
name: export-agent-session
description: Export a selected NanoClaw Claude provider transcript as Agent Session Record JSON Lines, including retained tool and model calls.
---

Run from the NanoClaw checkout with its pinned dependencies installed.
Use `ncl sessions list` to select the NanoClaw session. Locate that session's
Claude SDK continuation transcript in its container state under
`.claude/projects/<project>/<continuation>.jsonl`.
Verify the continuation belongs to the selected session before exporting.
Pass an explicit file. Do not search for or export the newest transcript globally.

```sh
pnpm exec tsx "${CLAUDE_SKILL_DIR}/scripts/export-agent-session.ts" \
  --session SESSION_ID --transcript SELECTED_TRANSCRIPT.jsonl \
  --format agent-session > session.jsonl
```

The utility preserves native file order, text, response IDs, served models,
inclusive input token counts, reasoning summaries and tool calls and results.
It excludes signatures and known credential fields. Review exports before sharing.
The header declares missing mailbox delivery, approvals, edits, commits,
lineage, settings and other unsupported evidence. A transcript from one provider
continuation covers only that continuation. Export other continuations separately.
Other providers need their own native transcript mapping.

Run `pnpm exec vitest run .claude/skills/export-agent-session/scripts/export-agent-session.test.ts`.
Run `pnpm exec tsc --noEmit --module nodenext --moduleResolution nodenext --target es2022 --skipLibCheck .claude/skills/export-agent-session/scripts/export-agent-session.ts`.
This utility reads an explicitly selected file and leaves no installed code or configuration.

## Troubleshooting

Rows with one response ID share a single model call. Later usage snapshots
replace earlier counts. Repeated native record IDs or tool results fail before output. Unsupported records and incomplete
lines produce gaps. Stop the selected session to obtain a stable file.
