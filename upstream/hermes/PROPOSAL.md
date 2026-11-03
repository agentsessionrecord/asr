# Agent Session Record export for Hermes

Export a saved session as Agent Session Record so local tools can search and review its recorded work.

This adds `agent-session` to the existing `hermes sessions export --format` menu. It reads the stored SQLite history and uses the existing `--session-id` selector and positional output argument. One explicit ID without output writes JSONL to stdout. An output directory receives one file per selected session. `-` also selects stdout. Existing output files are refused.

The export retains stored text, readable reasoning, tool calls, model-facing results and native message order. Inactive rows remain available. Explicit parent markers and shared message UIDs preserve supported lineage and copies. Compaction summaries carry a following gap. Tool outcomes remain unknown when storage does not establish them.

Usage, inference boundaries, approvals, complete settings, offered tools, file edits, commits and complete copy detection are missing. Unsupported or corrupt stored content becomes a gap. No audit store, CLI aliases or dependency is added.

```sh
hermes sessions export --format agent-session --session-id SESSION_ID
hermes sessions export exports --format agent-session --session-id SESSION_ID
hermes sessions export exports --format agent-session
```

Source: [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent), base `b7736eca98cc6919b7b7f1d52dc1c45946793648`. Apply the ordered patches in [manifest.json](manifest.json) with `git am` in a clean checkout at that base.

Output uses ASR 0.1 with `producer.method: native`. Known credential fields or recognized secret text are excluded where the source mapping supports them. Review exports before sharing. Filtering cannot identify every secret.

The native fixture and ASR sample are synthetic. [TEST-RESULTS.md](TEST-RESULTS.md) states the current verification results and remaining limits. Structural validation does not prove complete capture.
