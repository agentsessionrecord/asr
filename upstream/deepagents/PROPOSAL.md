# Agent Session Record export for Deep Agents Code

Export a saved session as Agent Session Record so local tools can search and review its recorded work.

This adds `dcode threads export --format agent-session` to Deep Agents Code 0.2.4. One explicit thread without an output directory writes JSONL to stdout. Repeat `--session` to select threads with directory output. With an output directory and no IDs, all stored threads are selected. Existing output files are refused.

The exporter reads a consistent read-only snapshot of root-namespace SQLite message writes in native replay order. LangChain message types provide text, tool arguments and explicit tool outcomes. Revisions and result updates occupy their final observation. Removal markers do not erase captured work. Corrupt writes become gaps. Large native argument integers become exact decimal strings. Pickle fallback is disabled.

Message boundaries do not establish model calls. Usage, historical models, complete reasoning, approvals, settings, instructions, tools, timestamps, edits, commits, child sessions and copies remain incomplete. Offloaded history and nested checkpoint namespaces are not recovered. The change stays in `libs/code` and adds no dependencies or lockfile changes.

```sh
dcode threads export --format agent-session --session THREAD_ID
dcode threads export --format agent-session --session THREAD_ID --output exports
```

Source: [langchain-ai/deepagents](https://github.com/langchain-ai/deepagents), base `89f85affc20ea22d9a1ddb5821987660368b7b8b`. Apply the ordered patches in [manifest.json](manifest.json) with `git am` in a clean checkout at that base.

Output uses ASR 0.1 with `producer.method: native`. Known credential fields or recognized secret text are excluded where the source mapping supports them. Review exports before sharing. Filtering cannot identify every secret.

The native fixture and ASR sample are synthetic. [TEST-RESULTS.md](TEST-RESULTS.md) states the current verification results and remaining limits. Structural validation does not prove complete capture.
