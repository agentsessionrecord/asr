# OpenClaw ASR export plugin

Export a retained OpenClaw session as ASR for use in other session tools.
The primary form is a standalone plugin. It uses `definePluginEntry`,
`registerCli` and `readSessionTranscriptEvents` from the public plugin SDK.
It needs no core changes or private database imports.

`openclaw asr-export` takes an agent, session key, native session ID and new output
file. It preserves retained text and tool call and result evidence. It writes
mode 600 and refuses to overwrite a file. Known credentials and signatures are
excluded. Unsafe parsed integers fail instead of exporting rounded values.

A prefix gap states the public projection's scope. Model calls, usage, approvals,
settings, edit receipts, archives and provider state remain declared losses.
The plugin does not supply the tamper evidence discussed in
[#171272](https://github.com/openclaw/openclaw/issues/171272).
Its retained history scope is relevant to
[#154482](https://github.com/openclaw/openclaw/issues/154482).

A secondary eight-commit core series keeps the fuller SQLite snapshot exporter
available for review. It adds side-store evidence only where native facts support
it. Each commit adds fewer than 900 lines. The plugin is the preferred installable
form. Neither form creates a parallel audit store.

Plugin tests cover text, tool pairing, credential removal, unsafe numbers and
public SDK CLI registration. Secondary tests cover snapshot boundaries, completion,
reasoning, command registration and optional discovery. Package checks validate
synthetic samples and replay the eight commits from the pinned base.

Source: [https://github.com/openclaw/openclaw](https://github.com/openclaw/openclaw).
Base: `05a73c2679f5c7bb660e5f391ee89dd5e618f565`.
