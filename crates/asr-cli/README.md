# asr

The `asr` CLI converts, collects, validates, redacts and replays session files.
It also finds recorded edit and commit evidence behind a Git line.

## Install

Use Rust, Git, Node.js 22.13 or later and pnpm 12.11.2. From the repository root:

```sh
pnpm --filter @agent-session/validate install --frozen-lockfile
cargo install --path crates/asr-cli --locked
```

Keep the repository available. Set `ASR_REPO_ROOT` to its absolute path when
running the installed binary elsewhere. Validation, collection and the session
tools need the Node validator and its installed dependencies.

## Use

```sh
cargo run -p asr-cli -- agents
cargo run -p asr-cli -- convert --agent codex native-logs --out converted
cargo run -p asr-cli -- validate --summary converted
```

`convert` accepts a file or directory. It prints session and record counts and
source diagnostic counts as JSON. Use `--max-record-bytes` to change the 16 MiB
record limit. No session identity produces exit code 1. Other failures use 2.

`validate` finds `tools/validator/bin/asr-validate.js` from the current repository,
the source checkout, or `ASR_REPO_ROOT`. It requires Node and the validator's
installed dependencies. It preserves validator exit codes. `--json` and `--summary`
are forwarded. A missing validator produces a clear error and exit code 2.

| Command | What it reads or writes | Limits and examples |
| --- | --- | --- |
| `agents` | Lists supported native source profiles | [Converter coverage](../asr-convert/README.md) |
| `convert` | Writes one ASR stream per recorded native session | [Source mappings and losses](../asr-convert/README.md) |
| `validate` | Checks streams, annotations and manifests | [Validator rules](../../tools/validator/README.md) |
| `collect` | Discovers native logs, converts changes and stores exact files | [Collection and storage](../asr-collect/README.md) |
| `receive` | Accepts authenticated files and writes receipt manifests | [Receiver setup](../asr-collect/README.md#receive-uploads) |
| `redact` | Writes a derived copy with selected data removed or masked | [Redaction selectors](TOOLS.md#redact-a-file) |
| `blame` | Reports separate edit and commit evidence with record citations | [Local Git and session lookup](TOOLS.md#find-evidence-behind-a-line) |
| `replay` | Sends one reconstructed model request and writes a fork session | [Private provider settings](TOOLS.md#re-ask-one-model-call) |

Use `asr COMMAND --help` for options. The offline [viewer](../../apps/viewer/README.md)
is a separate app. This binary has no `view` subcommand. Exporters and importers
also have their own entry points.

## Capture limits

Conversion cannot restore facts absent from native storage. Each adapter states
its losses. Collection receipts establish received bytes, not complete capture.
Validation checks format and relationships, not authorship or safe sharing.
Blame needs local Git objects and recorded evidence. Missing links stay unresolved.
Replay reconstructs context and stops after one model response. It does not
execute tools or rebuild a sandbox. Redaction patterns cannot find every secret.
See the [session tool guide](TOOLS.md) for the detailed reader and output limits.

## Tests and status

The Rust workspace integration tests invoke the Node validator. On a fresh
checkout, install its dependencies before running either Cargo test command.
Cargo does not install Node packages. Missing validator dependencies fail the
integration tests rather than skip validation.

```sh
pnpm --filter @agent-session/validate install --frozen-lockfile
cargo test --workspace
cargo test -p asr-cli
node tools/validator/bin/asr-validate.js --summary crates/asr-cli/tests/fixtures
cargo build -p asr-cli --locked
python3 crates/asr-cli/scripts/check-blame.py --binary target/debug/asr
```

The blame check converts synthetic Codex and Claude Code edits, validates their
streams and commits the recorded content in temporary Git repositories. It checks
partial and multi-line replacements without trailing newlines, plus written
lines shifted by later edits. It makes no model requests. The timing regression
checks 5,000 sessions that all match one line in under five seconds and counts
the Git processes.

Set `ASR_TEST_CLAUDE_HISTORY` to a native history directory to opt into the bounded
private replay check in CI. The check excludes possible credentials before writing
scratch files. It prints counts, redirects file paths into a temporary repository
and deletes that repository after the check. It makes no model requests.

The suite uses synthetic native logs, local Git repositories and mock HTTP
responses. Redaction covers the sample and example streams. Replay tests capture
OpenAI and Anthropic requests, including Codex outputs without inference links.
Current model endpoint coverage is partial. The [registry](../../registry.json)
separates current checks from the endpoint evidence in [live-test.json](live-test.json).
These checks do not qualify a complete agent rerun or a production endpoint.
The [collector](../asr-collect/README.md#checks) and
[converter](../asr-convert/README.md#tests) describe their own checks.
