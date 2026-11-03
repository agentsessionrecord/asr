# Workspace checks

Run `bash scripts/ci.sh` from any directory. The summary lists checks that pass,
fail or skip. A failed check gives the command a nonzero exit code after the
remaining checks run.

The white paper builds before the strict site build because the site requires
its PDF. Empty Rust, JavaScript, Python and Go trees skip their checks. Once a
tree has source or a package manifest, a missing tool or dependency is a failure.

`check-registry.mjs` checks the registry schema, unique IDs and local paths.
`check-writing.mjs` checks public Markdown prose using the documentation writing
rules. It skips code, URLs, frontmatter and comments. The author disclosure and
agent registry rows have narrow exceptions.

`check-privacy.mjs` scans `samples/` and fixture paths throughout the source tree,
including `fixtures`, `__fixtures__`, `testdata` and fixture filenames. It looks
for common tokens, private keys, account identifiers, home paths and sensitive
assignments. It reports only filenames, line numbers and rule codes. It skips
dependency and build output directories outside fixture trees. These patterns cannot determine
whether arbitrary text came from a real session. Review synthetic data before
committing it.

Add generated-file checks with a package `check:generated` script. Add checks
for other languages directly to `ci.sh`. Test new check behavior with
`pnpm test` and keep fixtures synthetic.

## Setup, output and status

Install the toolchains and dependencies in the
[contribution guide](../CONTRIBUTING-tools.md) before running CI.
The commands write check summaries and generated build output. They do not
record an agent session. Passing checks do not qualify untested host versions,
cloud services or private data for sharing.

`check-tool-docs.mjs` checks registered tools against the site catalog. It
requires a nearby README, a catalog row with the current test status, navigation
entries and working local Markdown links. Repository README URLs are resolved
against this checkout. The check does not request remote pages.
When `SECURITY.md` exists, the catalog must link to it and its local Markdown
links must resolve. New registered tools, including test suites and security
checks, require catalog rows too.

The [end-to-end suite](../tests/e2e/README.md) adds offline harness checks.
Its clean-container live run is optional. Enable it with `ASR_TEST_E2E=1` and
an explicit private `ASR_PROXY_KEY_FILE`. The summary reports a skip when it is
disabled.

`check-security.py` runs synthetic checks for private storage, credential echoes
and bounded readers. CI runs it in the Python workspace. Read
[SECURITY.md](../SECURITY.md) for the threat model and remaining limits. Passing boundary checks do not make recordings safe to share.

Run `node --test scripts/test/*.test.mjs` for the checker's synthetic failure
cases and the other script tests. Independent live testing is not applicable
to these offline workspace checks.
