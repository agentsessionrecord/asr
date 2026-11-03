# Shelley ASR export

The patch adds a small standalone database export command and `DB.WriteAgentSession`. It opens an existing `shelley.db` in read-only mode. It changes neither the database schema nor saved messages.

Source: https://github.com/boldsoftware/shelley. Pinned base: `3df54607e37a808362437f96f17d1d276b74684a`.

Apply `patches/*.patch` with `git am` in a clean writable checkout at the pinned base. Build the patched source using its own instructions.

```sh
go run ./cmd/shelley-export --db /path/to/shelley.db \
  --session SESSION_ID --format agent-session > session.asr.jsonl
```

Native sequence order supplies text, retained reasoning, supported inline images, tool arguments, IDs, final results, and timestamps. Repeated tool results fold into the last result at its completion position. Human authorship is supplied only when the native row records a user email. Opaque reasoning and provider metadata are excluded. Unsupported content becomes a gap. Models, usage, approvals, settings, file changes, commits, and relationships are declared missing. The export is not a redactor. Review conversation content before sharing.

Go 1.27.3 is required. Focused checks are `go test ./db ./cmd/shelley-export`, `go vet ./db ./cmd/shelley-export`, and `go build ./cmd/shelley-export`. `python3 upstream/shelley/reproduce.py /path/to/patched-checkout` creates a synthetic database, runs the native command, compares the sample, and validates it. The standalone command does not use the web UI.

Run these package checks from the ASR repository:

```sh
node upstream/shelley/check.mjs
node upstream/shelley/reproduce.mjs /path/to/patched-checkout
```

Package reproduction replays the patch in a temporary Git index. It preserves the checkout and does not compile the agent. [TESTS.json](TESTS.json) records the current verification scope. No current model session was run.

Shelley requires a CLA. The export preserves immutable messages and needs no schema review. The database location is documented by shelley.dev, which currently offers no export.
