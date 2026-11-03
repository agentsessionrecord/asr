# Contributing tools

Read [the specification](spec/overview.md) before writing or reading ASR.
Keep the Node validator in `tools/validator`.

| Directory | Contents |
|---|---|
| `crates/` | Rust core, converters and command line tools |
| `packages/` | TypeScript and JavaScript libraries |
| `python/` | Python libraries in the uv workspace |
| `go/` | Go module and libraries |
| `plugins/<agent>/` | Agent plugins and hook recorders |
| `recorders/<name>/` | Gateway and Agent Client Protocol recorders |
| `importers/<name>/` | Vendor and other source importers |
| `exporters/<name>/` | Exports to formats and services |
| `apps/<name>/` | Viewers and integrations |
| `upstream/<agent>/` | Native export patches and proposals |

Add converters to `crates/asr-convert`. Keep source discovery, parsing and
agent mappings separate. Add a plugin, importer or exporter under its named
directory. Each tool needs a README with setup, supported versions, capture
limits and test commands.

Add Rust crates to the root `Cargo.toml`. The pnpm workspace includes
`tools/validator`, `site`, `whitepaper` and `packages/*`. Python package
manifests live under `python/*` and the Go module starts at `go/go.mod`.

Add an entry to [registry.json](registry.json). Use a unique ID, a relative
repository path, a language, a status and a live-test status. Built entries need
an existing path. For work outside this repository, use `elsewhere` and give
its revision and public HTTPS location. An external entry's
`path` is its intended destination in this repository. A prior live test does
not establish compatibility with the current spec.

Install Node.js 22.13 or later and pnpm 12.11.2. Run `pnpm install --frozen-lockfile`
at the root. The root lockfile covers all Node packages. The white paper build
needs Google Chrome or Chromium. Set `CHROME` if it is outside the command path.
Rust, uv with Python 3.11 or later, and Go 1.23 or later are needed when their
source trees have code.

Run the checks from the repository root:

```sh
bash scripts/ci.sh
```

CI runs existing validator checks, the white paper and strict site builds,
registry and writing checks, and the fixture privacy scan. It also runs Rust
formatting, clippy and tests, pnpm package tests, Python tests and Go tests when
those trees have code. Empty trees appear as skipped in the summary. CI checks
committed, staged and unstaged whitespace.

Give each pnpm package a `test` script. Use `check:generated` to verify generated
files without changing them. Put Python tests under `python/` and use the root
`dev` dependency group for test dependencies. CI installs all Python workspace
members before running pytest. Go tests use `go test ./...` in `go/`.

Use synthetic fixtures. Never commit real session histories or credentials.
For every converter and recorder mapping, publish synthetic native inputs,
the ASR they produce and the source versions supported. Recorder inputs can
be hook payloads or connection messages.
Validate every produced ASR file with `node tools/validator/bin/asr-validate.js`
and explain warnings. The privacy scan covers samples and fixture paths across
all languages. Review the diff for sensitive data as well.

Write public docs in plain English with short sentences. Keep source facts and
capture limits clear. Record live-test results honestly. Use `partial` when only a focused export
function or a substitute entry point was exercised. Publishing packages,
sending patches and deploying services require a separate release task.

Each upstream package has `PROPOSAL.md`, `manifest.json`, `patches/`,
`samples/native/`, `samples/asr/`, `check.mjs` and `reproduce.mjs`.
The manifest pins the source base and each patch commit in application order.
It hashes every packaged file. Run a package's reproduce script with an upstream
checkout to replay its series in a temporary Git index and run the sample checks.
The checkout stays unchanged. Native export scripts are kept beside it when the
sample needs the upstream build environment.
