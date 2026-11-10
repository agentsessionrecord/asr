# Agent Session Record export for Shelley

This patch adds a small standalone export command and `DB.WriteAgentSession` to [Shelley](https://github.com/boldsoftware/shelley) for ASR output. It opens an existing `shelley.db` read-only and changes neither the schema nor saved messages. The pinned base is `3df54607e37a808362437f96f17d1d276b74684a`. [Apply the patch](../README.md#apply-a-patch) in a clean checkout at that base. Building needs Go 1.27.3.

```sh
go run ./cmd/shelley-export --db /path/to/shelley.db \
  --session SESSION_ID --format agent-session > session.asr.jsonl
```

Native sequence order supplies text, retained reasoning, supported inline images, tool arguments, IDs, final results and timestamps. Repeated tool results fold into the last result at its completion position. Human authorship is set only when the native row records a user email. Opaque reasoning and provider metadata are left out, and unsupported content becomes a gap. Models, usage, approvals, settings, file changes, commits and relationships are declared missing. The export does no redaction, so review the content before sharing. The command does not use the web UI.

## Checks

```sh
node upstream/shelley/check.mjs
node upstream/shelley/reproduce.mjs /path/to/patched-checkout
```

See [package checks](../README.md#check-a-package). The focused upstream checks are `go test ./db ./cmd/shelley-export`, `go vet ./db ./cmd/shelley-export` and `go build ./cmd/shelley-export`. `python3 upstream/shelley/reproduce.py /path/to/patched-checkout` creates a synthetic database, runs the native command, compares the sample and validates it. [TESTS.json](TESTS.json) records the current scope. No live model run covers this revision.

Shelley requires a CLA. The patch needs no schema review. The shelley.dev docs give the database location and offer no export.
