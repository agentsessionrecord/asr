# ASR Sessions for VS Code

Show recorded session evidence behind a local Git line. Open a matched session
in the bundled offline ASR viewer. Install `asr` with the `blame` command first.
See [the CLI tools](../../crates/asr-cli/TOOLS.md).

## Install locally

Use Node.js 22.13 or later, pnpm 12.11.2, Git and VS Code 1.109.0 or later.
From the repository root:

```sh
pnpm install --frozen-lockfile
pnpm --dir apps/vscode run build
code --extensionDevelopmentPath="$PWD/apps/vscode" ./project
```

The build includes the existing viewer. It needs no running server.
Run `pnpm --dir apps/vscode run package:local` from the repository root to build
`target/asr-editor-0.1.0.vsix` with the pinned VS Code packager. Install it with
**Extensions: Install from VSIX**. No marketplace registration is needed. This repository does not
publish the extension.

Set these values in VS Code user settings. Stores must be absolute local paths.
The executable value is a binary path or a program on PATH, with no arguments.

```json native
{
  "asr.executable": "/opt/asr/bin/asr",
  "asr.sessions": ["/work/asr-store"],
  "asr.annotations": ["/work/asr-store/rewrite.annotations.jsonl"]
}
```

These settings have machine scope. A repository cannot set an executable or
store through workspace settings. Trust the workspace before using ASR.
Remote and virtual filesystems are not supported.

## Read line evidence

Hover over a saved line. **Edited by** and **Committed by** stay separate.
The hover includes record citations, the causing call, recorded human prompt
parts, the served model or a labeled requested model, and recorded approvals.
Missing links stay unresolved. Earlier matching edits are shown as alternatives.
Credit to a person or an untracked external edit keeps that label.

The display also includes the CLI's declared losses, gaps, parse diagnostics,
related sessions and source error count. Copies receive no work credit.
A match is recorded evidence. It does not prove authorship.

Choose **ASR: Show Sessions Behind This Line** from the editor menu for a larger
panel. Choose **Open session in viewer** in either view. You can also run
**ASR: Open Session in Viewer** and enter a session reference from the evidence.
The resolver uses headers in the configured store. Missing and duplicate
identities stay unresolved. Filenames are never taken from recorded references.

The viewer opens one session at a time. Related sessions and annotations are
not loaded automatically. Their links stay unresolved until you open the files
with the viewer's local file picker. That picker can also open larger files.
The automatic bridge accepts files up to 64 MiB and headers up to 64 KiB.
Store scans stop after 10,000 entries or 32 nested directories.

Unsaved buffers receive a save notice. A changed document discards a pending
result. There is no evidence cache. Git checks and session reads run locally.
Lookups have a 15 second deadline and a 16 MiB output limit. An unavailable or
older CLI, invalid store or non-Git file produces a notice.

Recorded text is displayed as text. Recorded commands, resource URLs and
Markdown cannot run or load remote content. Only the extension's own viewer
command is enabled in its generated links. The viewer blocks network requests
and does not change the session file. It makes no safe-sharing claim.

## Checks

Run the following from the repository root:

```sh
bash apps/vscode/check.sh
```

This builds the real CLI and viewer, checks TypeScript, runs integration tests,
and launches the VS Code extension test harness. Linux needs Xvfb when no display
is available. The first harness run downloads VS Code 1.109.0 into a dependency
cache. The Chromium test uses the viewer's Playwright browser or `CHROME`.

Tests cover every session in `samples/` and `examples/`, a synthetic local Git
repository, copies, approvals, losses, exact numeric values, ambiguous stores,
symlinks, cancellation, dirty files and hostile content. Synthetic ASR files
pass the Node validator. Temporary sessions and editor profiles are removed.
Both editor checks are included in `scripts/ci.sh`.
