# Native export packages

Each directory adds Agent Session Record (ASR) export to one agent. Most hold a source patch series and a short proposal for the agent's maintainers. OpenClaw also ships a standalone plugin, Pi an extension and NanoClaw a skill, and their source patches are kept as secondary references. DeepSeek Harness has the unofficial `dsh-plugin-asr-export` plugin and no core patch. The [patch catalog](../site/pages/tools/patch.mdx) lists every package with its test status.

A source patch package contains:

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

`PROPOSAL.md` describes the user benefit, the native source and what the mapping leaves out. `manifest.json` pins the upstream base, the final commit, the ordered patches and a digest for every file, with other source details under `provenance`. Samples hold synthetic data only. Every package writes ASR 0.1 with `producer.method: native`.

## Apply a patch

Set `ASR_PACKAGE` to the package's absolute path and run this in a clean checkout of the upstream project at the pinned base:

```sh
git am "$ASR_PACKAGE"/patches/*.patch
```

Then build the agent with its own instructions. The ASR CLI does not install these patches. To remove one, build from a clean unpatched checkout. Files you already exported stay where they were written.

No pattern filter catches every secret, so keep exports private and review them before you share them. A valid export does not show that capture was complete.

## Check a package

From the repository root:

```sh
node upstream/AGENT/check.mjs
node upstream/AGENT/reproduce.mjs /path/to/upstream-checkout
```

`check.mjs` checks the layout, file digests, patch syntax, privacy and the ASR samples, then runs the package's contract tests. `reproduce.mjs` needs both pinned commits in an existing checkout. It replays the patches in order through a temporary Git index, compares the result with the final commit and runs the package check, leaving the checkout's files, branch and index as they were. Neither command builds the agent or calls a model, so a passing check is not an upstream build or a live run. Each README reports those results separately.

Plugin packages run their own checker and replay against the pinned API instead. Some packages add a native check, described in their README.

See the [tools contribution guide](../CONTRIBUTING-tools.md) to add a package.
