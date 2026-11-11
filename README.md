<div align="center">
  <br>
  <a href="https://agentsessionrecord.org">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="site/pages/logo/dark.svg">
      <img alt="ASR, Agent Session Record" src="site/pages/logo/light.svg" width="420">
    </picture>
  </a>
  <h3>An open format for agent sessions</h3>
  <p>
    <a href="https://agentsessionrecord.org">Website</a>
    &nbsp;·&nbsp;
    <a href="https://agentsessionrecord.org/get-started/quick-tour">Quick tour</a>
    &nbsp;·&nbsp;
    <a href="spec/overview.md">Specification</a>
    &nbsp;·&nbsp;
    <a href="crates/asr-cli/README.md">CLI</a>
    &nbsp;·&nbsp;
    <a href="https://agentsessionrecord.org/downloads/agent-session-record-whitepaper.pdf">White paper</a>
  </p>
  <p>
    <img alt="Format 0.1" src="https://img.shields.io/badge/format-0.1-18181b">
    <img alt="License Apache 2.0" src="https://img.shields.io/badge/license-Apache%202.0-18181b">
  </p>
  <br>
</div>

Coding agents all log the same things: prompts, replies, tool calls, file edits and commits. Each one uses its own format. Agent Session Record (ASR) is an open format for exporting sessions, so a harness exports once and any tool can read it. [ACP](https://agentclientprotocol.com/) covers steering an agent while it runs. ASR covers the exported session file. It doesn't change how a harness stores its own logs.

ASR is a file format, not a service. Session files stay on your machine unless you choose to share them. Use them to search past sessions across agents, find the session behind a line of code, or move history between tools.

Sessions are JSON Lines because agents append while they run and the file survives a crash. The [tables exporter](exporters/tables/) writes Parquet for analysis across many sessions.

```sh
cargo install --path crates/asr-cli --locked
asr convert --agent claude-code ~/.claude/projects --out sessions
```

## Tools

See the [tools guide](site/pages/tools/) for setup, examples and test status.

- [CLI](crates/asr-cli/README.md): convert native logs, collect sessions, redact, replay and trace code with blame.
- [Plugins](plugins/README.md) and [recorders](recorders/): capture sessions as agents work.
- [Viewer](apps/viewer/README.md): open session files locally.
- [Exporters](exporters/): send records to search, tables and observability tools.
- [Native export patches](upstream/README.md): proposals and local patch packages for agent maintainers.

Read the [tools contribution guide](CONTRIBUTING-tools.md) for dependencies and checks.

## Repository layout

| Path | Contents |
|---|---|
| `spec/` | The specification. |
| `guides/` | Guides for integrations, replay, company use and audits. |
| `agents/` | Agent names, the JSON list and converter notes. |
| `schema/v0/` | Schemas for session records, annotations, discovery files and collection manifests. |
| `examples/` | Example session streams, annotations and a collection manifest. |
| `conformance/` | Validator fixtures. |
| `tools/validator/` | The reference validator. |
| `crates/` | Rust CLI, converters and collector. |
| `packages/`, `python/`, `go/` | Types and writers. |
| `plugins/`, `recorders/` | Agent hooks and connection recorders. |
| `apps/` | Viewer, editor integrations and forge tools. |
| `importers/`, `exporters/` | Data imports and exports. |
| `upstream/` | Native export proposals and patches. |
| `site/` | Documentation site sources and build. |
| `whitepaper/` | White paper source and HTML/PDF build. |

## Build the documentation

```sh
pnpm --dir whitepaper install
node whitepaper/build.mjs
pnpm --dir site install
node site/build.mjs
```

The PDF build needs Chrome or Chromium. See [site instructions](site/README.md) and [white paper instructions](whitepaper/README.md).

The [agent list](agents/index.md) and [JSON data](agents/agents.json) are maintained together by pull request. Converter notes name their supported source versions and known losses.

## License

[Apache License 2.0](LICENSE).
