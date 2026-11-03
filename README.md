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
    <img alt="Format 0.1 draft" src="https://img.shields.io/badge/format-0.1%20draft-18181b">
    <img alt="License Apache 2.0" src="https://img.shields.io/badge/license-Apache%202.0-18181b">
  </p>
  <br>
</div>

Agent Session Record (ASR) is an open format for recording what an AI agent did in a session. It keeps prompts, replies, tool calls, file edits and commits in JSON Lines, so tools can search work across agents and connect code to the session behind it.

## Tools

See the [tools guide](site/pages/tools/) for setup, examples and test status.

- [CLI](crates/asr-cli/README.md): convert native logs, collect sessions, redact, replay and trace code with blame.
- [Plugins](plugins/README.md) and [recorders](recorders/): capture sessions as agents work.
- [Viewer](apps/viewer/README.md): open session files locally.
- [Exporters](exporters/): send records to search, tables and observability tools.
- [Native export patches](upstream/README.md): proposals and local patch packages for agent maintainers.

Build the CLI with `cargo install --path crates/asr-cli --locked`. Read the
[tools contribution guide](CONTRIBUTING-tools.md) for dependencies and checks.

## Repository layout

| Path | Contents |
|---|---|
| `spec/` | Eight normative core pages. |
| `guides/` | Guides for integrations, company use, audits and replay. They add no requirements. |
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
