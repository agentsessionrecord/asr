# Native export patches

Each agent directory holds local patches and a short proposal for native ASR
export. Each package uses the same layout.

```text
README.md
PROPOSAL.md
manifest.json
patches/0001-*.patch
samples/native/
samples/asr/session.jsonl
check.mjs
reproduce.mjs
```

The proposal describes the user benefit, supported source and mapping limits.
The manifest pins the upstream base, final commit, ordered patch series and file
digests. Additional source metadata is kept under `provenance`. Sample inputs
and outputs contain synthetic data.

Run the package check from the repository root. It checks the layout, file
digests, patch syntax, privacy and ASR samples, then runs the agent's contracts.

```sh
node upstream/AGENT/check.mjs
node upstream/AGENT/reproduce.mjs /path/to/upstream-checkout
```

The reproduce command uses the pinned commits in an existing local checkout.
It replays the patches in order through a temporary Git index and compares the
result with the final source tree. It also runs the package check. The command
preserves the checkout's files, branch and index. It does not build the agent or
make model requests. Agent-specific instructions describe native export checks.

See [the tools contribution guide](../CONTRIBUTING-tools.md).

## Find a patch

Each package's README covers local evaluation, native use, capture limits and test
status. The Codex package asks for design feedback and includes reference code. The [site patch catalog](../site/pages/tools/patch.mdx) links all packages.
Package checks run without a model or service. A passing package check does not
establish a full upstream release build or a live agent run. The individual
README and proposal distinguish those results.
