# DeepSeek Harness session export plugin

Download a saved session as Agent Session Record without changing the harness. This unofficial community plugin adds `GET /api/session.asr?sessionId=SESSION_ID` through the authenticated Host connection.

The plugin uses a detached session-query observation and preserves source order, text, readable reasoning, calls, and final results. It excludes inherited events with a gap rather than crediting copied history as new work. The header declares unavailable usage, model identity, settings, approvals, relationships, media, edits, and commits. Provider replay state and unknown payloads are excluded.

Install the local tarball with `dsh plugin --profile web add /path/to/package.tgz` and load the supplied Cordis overlay with `dsh web --patch /path/to/cordis.patch.yml`. An authenticated owner can download the ASR route. Unloading the plugin withdraws it.

The package is self-contained and ready to move to its own repository. [TESTS.json](TESTS.json) records checks against the current public API.
