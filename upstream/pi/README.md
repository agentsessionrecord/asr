# Agent Session Record export for Pi

This Pi extension exports the current session as ASR. Pi core needs no change. The source patch adds the same extension to [Pi](https://github.com/earendil-works/pi) as an example with focused tests. The pinned base is `8f9446a06027b075bf885189ceb0983565662174`.

Install the bundled `extension/` directory as a local Pi extension:

```sh
pi install ./extension
```

In Pi, run `/export-asr session.asr.jsonl`. The command reads the current saved session and writes a new file with mode 600, and it never overwrites a file. Offline, with Node 22.16 or later:

```sh
node extension/cli.ts \
  --session native-session.jsonl --format agent-session --output session.asr.jsonl
```

The extension keeps the whole native v3 session tree in file order, including abandoned branches. It exports text, supported reasoning, tools, final results, summaries, injected messages and identified model calls with inclusive usage. Signatures and known credential fields are left out. It does not reconstruct media, approvals, edits, commits, child lineage or opaque provider state. Corrupt or unsupported input fails before any output is written.

## Checks

```sh
node upstream/pi/check.mjs
node upstream/pi/reproduce.mjs /path/to/patched-checkout
node upstream/pi/reproduce-native.mjs /path/to/patched-checkout
```

See [package checks](../README.md#check-a-package). The third command reproduces the native fixture. Focused export tests, native fixture reproduction and an isolated local install and run of the extension pass. The root check and offline build fail on an existing Copilot provider type error in `packages/ai/src/providers/github-copilot.ts:33` (TS2322), in a file the patch does not change. [verification.json](verification.json) has the current status. No live model run covers this revision.
