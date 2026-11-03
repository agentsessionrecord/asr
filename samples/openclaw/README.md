# OpenClaw sample

Agent version and original producer: OpenClaw 2026.10.7, with method `native` and source `openclaw-sqlite`.

The isolated synthetic task requested `Reply exactly: ASR synthetic sample. Do not call any tools.` It used an empty temporary state directory and configuration, Node 26.12.1 and an explicitly configured model through an OpenAI-compatible endpoint. The native exporter ran `openclaw sessions export --format agent-session --agent main --all --output <directory>`.

`native/session.jsonl` contains decoded `transcript_events` in SQLite sequence order. `native/snapshot.json` contains the matching session window, node and selected side-store rows. Maps are stored as entry arrays. The exported stream is `asr/session.jsonl`. This sample was edited. One tool-description phrase is replaced with `when finished with it` in both event and ASR files. Routing metadata in the event and ASR files uses a synthetic model and an example endpoint. The native snapshot is unchanged. Temporary `/tmp/` paths and session IDs belong to this synthetic run. The sample records offered tool definitions and no tool invocation. No credential store or configuration file is included.

The edited ASR producer is `asr-sample-editor` version `1.1`, with method `converter` and source `agent-session-record-0.1`. Changed records carry `truncated: true`. The header declares `sample_text` and `sample_routing` and links the original ASR through `derivedFrom.sha256`. Other native observations, identities and times are retained.

Validate the ASR from the repository root:

```sh
node tools/validator/bin/asr-validate.js --summary samples/openclaw/asr
```

SHA-256 values cover exact data file bytes, including newlines.

| File | SHA-256 |
|---|---|
| `asr/session.jsonl` | `f301f5affb7aeb19be2f7d9ee40455e24fd5dd7a6569fc7b9d8e9631e3ef3d1d` |
| `native/session.jsonl` | `e37deb17abf4775cd41275af2a3af1274a2efe5589982b20e37893527ad71118` |
| `native/snapshot.json` | `395b8fe48d96179bd8e5f51f39c11d4975c4ab0e6107edd704381bbb034b6a22` |
