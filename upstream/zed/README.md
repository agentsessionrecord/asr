# Agent Session Record export for Zed

This patch adds an ASR export example to the agent crate of [Zed](https://github.com/zed-industries/zed). The pinned base is `57dfd54adebb6d4a62cd1c42d397acb667a71c0a`. [Apply the patches](../README.md#apply-a-patch) in a clean checkout at that base. The [proposal](PROPOSAL.md) gives runtime requirements, build steps and output options.

```sh
cargo run -p agent --example export_agent_session -- \
  --format agent-session SESSION_ID THREAD.json > session.jsonl
```

A saved native DbThread JSON snapshot supplies retained text, reasoning, calls, structured or raw arguments, results and native user message IDs. Pass the database thread ID separately. Opaque provider state is left out, but there is no general secret redaction. Images, models, usage, approvals, settings, relationships and event times are absent, and the order of the result map does not show execution order. The patch adds no GUI action and no database discovery.

## Checks

```sh
node upstream/zed/check.mjs
node upstream/zed/reproduce.mjs /path/to/upstream-checkout
```

See [package checks](../README.md#check-a-package). Focused tests, the type check, Clippy and format checks pass, and [refresh.json](refresh.json) has the results. No live model run covers this revision.

Upstream requires a staff-confirmed discussion and human review before a pull request.
