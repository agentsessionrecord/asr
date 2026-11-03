# Pi ASR extension

Source: [https://github.com/earendil-works/pi](https://github.com/earendil-works/pi).
Pinned base: `8f9446a06027b075bf885189ceb0983565662174`.

Install the bundled `extension/` directory as a local Pi extension. Pi core needs
no change. The source patch adds the same extension as an example with focused tests.

```sh
pi install ./extension
```

In Pi, use `/export-asr session.asr.jsonl`. The command reads the current saved
session and writes a new file with mode 600. It refuses to overwrite a file.
For offline use with Node 22.16 or later:

```sh
node extension/cli.ts \
  --session native-session.jsonl --format agent-session --output session.asr.jsonl
```

The extension preserves the whole native v3 session tree in file order, including
abandoned branches. It exports text, supported reasoning, tools, final results,
summaries, injected messages and identified model calls with inclusive usage.
It excludes signatures and known credential fields. It does not reconstruct media,
approvals, edits, commits, child lineage or opaque provider state.
Corrupt or unsupported input fails before output.

Native fixture reproduction:

```sh
node upstream/pi/reproduce-native.mjs /path/to/patched-checkout
```

## Package checks

The manifest pins the source base, patch commits and file digests. Apply the
ordered patches in a clean checkout at that base with `git am patches/*.patch`.
The package is not installed by the ASR CLI.

From the ASR repository root, run:

```sh
node upstream/pi/check.mjs
node upstream/pi/reproduce.mjs /path/to/patched-checkout
```

The second command checks replay in a temporary Git index. It preserves the
checkout and requires the pinned commits. It does not build the agent.
Native fixture reproduction is a separate check described below.

The refreshed project checks and fixture regeneration are awaiting execution.
See [verification.json](verification.json) for the current status. Existing
live evidence is historical and does not validate this revision. No live model
request was made for this refresh.

Keep exports private and review them before sharing. Pattern filters cannot
identify every secret. Valid ASR does not establish complete capture.
