# Container end-to-end test

This optional suite installs ASR into a clean Linux image. It records new
Claude Code, Codex and Pi sessions through an OpenAI-compatible or Anthropic-compatible endpoint. It converts
their native files, collects the ASR streams into a disposable MinIO container,
opens the downloaded files in Chromium and exports those same files.

## Run

Use Linux, Python 3.11 or later and Docker. Set the endpoint URLs and model names
with the arguments below or the corresponding environment variables. Both URLs
must use `127.0.0.1` with an explicit port. Use values you are allowed to use. The suite
uses the host network so a loopback endpoint has the same meaning inside the
runner container.

```sh
python3 tests/e2e/run.py --key-file /private/provider-key --sudo --openai-base-url "$ASR_OPENAI_BASE_URL" --openai-model "$ASR_OPENAI_MODEL" --anthropic-base-url "$ASR_ANTHROPIC_BASE_URL" --anthropic-model "$ASR_ANTHROPIC_MODEL"
```

Omit `--sudo` when your user can access Docker. The key file stays on the host.
The suite writes private provider settings after building the source image.
Only those settings are mounted into the runner. There is no Docker socket,
host home directory or native history mounted into it.

The Dockerfile pins Node, Rust, agent CLI and package-manager versions. Repository
dependencies use the committed pnpm and Cargo locks. Python table dependencies
have exact versions in their package manifest. Distribution packages and Python
build tools are resolved at image build time. The build needs access to package
registries and container registries. No package is published.

MinIO is built from source commit `0d7408fc9969`, release
`RELEASE.2025-04-22T22-12-26Z`, using the pinned Go builder in
`Dockerfile.minio`. `--minio-image` uses an existing local MinIO image instead.
It never implicitly pulls that override. `--report /private/e2e-result.json`
saves aggregate results to a new private file. Output contains codes and counts.
It contains no native session text, account identities or provider credentials.

## Checks

The test installs the Rust `asr` binary, Claude Code hooks, Codex hooks and the
bundled Pi extension from this checkout. It installs the viewer and the
OpenTelemetry, tables and search exporters from this checkout.

Each agent uses a separate empty home, configuration and working directory.
The endpoint key is stored only in provider settings that the agent reads. Every
model run first checks the selected provider and loopback base URL. Agent
processes receive an explicit environment without inherited credentials.
Startup catalog refreshes, telemetry and unrelated discovery are disabled where
the CLI supports it. The synthetic prompt requests one `printf` command and a
short reply. No account or browser login is needed.

The suite checks:

- All three installed plugins record one paired tool call and its output.
- Plugin identities match the sessions found in the new native logs.
- Native conversion retains the assistant reply for each agent.
- Every recorded, converted and downloaded ASR stream validates without errors.
- Collection uploads three exact converted files with matching SHA-256 metadata.
- Completed receipt manifests validate and name every uploaded digest and length.
- A second collection with the same state converts and uploads nothing.
- The viewer opens all three downloaded streams through its public file input.
- Every record is reachable through the viewer timeline, without page errors or network requests.
- OTLP logs cover all core records and preserve their payloads.
- Parquet records, DuckDB rows and search documents cover every input record.
- Parquet and search exports preserve each recorded payload, including vendor records.
- Search chunks are nonempty and the bundle passes its integrity check.
- Exporting leaves the downloaded ASR bytes unchanged.

Codex hooks declare assistant messages missing. Its native converter supplies
that coverage. Hook extension records can produce `unknown-type` and
`unknown-extension` validator warnings. They preserve observations outside the
core vocabulary. Other warning codes are reported for review. A warning does
not excuse a validation error.

The recorded run in [live-test.json](live-test.json) passed with zero errors.
It reported one `missing-tool-name` warning in converted output. The affected
call remains unnamed in ASR. The test reports that loss without filling a name
from a neighboring record. Vendor records and extension declarations account
for the other warnings.

The OpenTelemetry exporter reports and skips unknown vendor record types.
The suite checks the exact number of those diagnostics. It does not require
telemetry to act as an archive. Missing timing contracts can also omit spans
with a diagnostic. The source bytes remain in MinIO and the other exports.

All live session data, provider files, exporter outputs and local store data are
temporary. Cleanup removes the owned containers and task images. A failed
assertion returns a nonzero exit code. The suite does not reuse existing agent
homes, collect existing history, start child agents or contact public storage.

## CI

The offline harness checks always run in `scripts/ci.sh`. They verify private
provider files, endpoint rejection, environment isolation, build inputs and
diagnostic privacy. They need neither Docker nor a model service.

```sh
python3 -m unittest discover -s tests/e2e -p 'test_*.py'
ASR_TEST_E2E=1 ASR_PROXY_KEY_FILE=/private/provider-key ASR_TEST_DOCKER_SUDO=1 bash scripts/ci.sh
```

The live section appears as skipped unless `ASR_TEST_E2E=1`. That flag requires
explicit endpoint and model variables from the run example and an
`ASR_PROXY_KEY_FILE`. `ASR_E2E_MINIO_IMAGE` overrides the MinIO image.
CI preserves failures and continues to its other checks. The end-to-end suite
does not qualify production S3, hosted telemetry receivers, remote search
services or other agent versions.
