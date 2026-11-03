# ASR GitHub app

Find the recorded sessions behind a pull request. Post a neutral check run or a
summary comment with session links, separate edit and commit evidence, approvals,
known losses, gaps and unresolved references.

This directory contains app code. No GitHub App is registered. Tests use a local
HTTP mock and temporary Git repositories. GitHub production is not live-tested.

## Install and test

Use Node.js 22.13 or later, Git and the repository's pinned pnpm version. From the
repository root:

```sh
pnpm install --frozen-lockfile
pnpm --dir apps/github run build
pnpm --dir apps/github test
```

The app has no runtime package dependencies. TypeScript and Node types come from
the workspace. The root CI script runs the app checks.

## Configure the local store

Copy `config.example.json` to an operator-owned configuration file. Keep secrets
out of that file. Each repository entry binds a GitHub repository name and an
installation ID to a local Git repository root. Relative configuration paths
resolve beside the configuration file.

The store contains ASR session files and companion `.annotations.jsonl` files.
It is read recursively. Symbolic links are skipped. Session identity comes from
the header, never from the filename. Duplicate session identities stay unresolved
rather than selecting an arbitrary export. Supply one current export per session.

The local repository must already contain all relevant commit objects. The app
does not fetch, clone or check out code. A missing object stops the report. Supply
local branches or tags for abbreviated commit ID reachability checks.

`recordedRoots` explicitly maps repository roots recorded on another machine to
this local repository. Only map roots whose repository identity you have checked.
A recorded remote URL does not establish repository identity. Without this map,
recorded paths must match the actual local repository root. Relative file paths
also need the session's recorded `cwd`.

`sessionsBaseUrl` is an operator-selected HTTPS directory URL. A session reference
is appended as one encoded path component. Record links use a `record` fragment.
For example, the reference `com.example.agent:run%3A7` has a URL path ending in
`com.example.agent%3Arun%253A7`. The viewer or session service must support that
route and enforce its own access rules. Session URLs are generated, never fetched.

`apiUrl` defaults to the GitHub REST API. HTTPS enterprise API base paths are
supported. Plain HTTP is accepted only for loopback mocks. Recorded stream URLs,
webhook URLs and API pagination links never choose a request destination.

## Entry points

Set `ASR_GITHUB_APP_ID` to the app's numeric ID and
`ASR_GITHUB_PRIVATE_KEY_FILE` to an owner-only PEM file. Authentication uses a
short-lived RS256 app JWT and cached installation tokens. Tokens and response
bodies are excluded from logs.

Create a local JSON report and Markdown preview before enabling publication:

```sh
node apps/github/dist/cli.js report /srv/asr/github.json example/project 7 /tmp/asr-report.json
```

This command reads the configured GitHub API and writes two owner-only output
files. Existing output files are never overwritten. The second file is `/tmp/asr-report.json.md`. It does not publish a check
or comment. The JSON file contains the full metadata report.

The library entry points are `App.report`, `App.webhook`, `buildReport` and
`renderSummary` in the compiled `dist` directory. `buildReport` works offline with
a `Git` instance, a loaded store and an explicit pull request description.

To handle webhooks, set `ASR_GITHUB_WEBHOOK_SECRET` and run:

```sh
node apps/github/dist/cli.js serve /srv/asr/github.json
```

The listener binds to `127.0.0.1:8787`. `ASR_GITHUB_PORT` changes the port. The
endpoint is `POST /webhook`. A deployment would need its own HTTPS ingress. No
ingress, service registration or deployment is included here.

The handler verifies the SHA-256 signature over the raw request bytes. It accepts
`pull_request` events for opened, reopened, synchronize, ready_for_review and
closed actions. Repository and installation IDs must match the allowlist. It
reads the current pull request from the API and checks for a changed head before
publication. Webhook fields do not choose filesystem paths.

Use `mode: "check"` for check runs or `mode: "comment"` for comments. A check has
conclusion `neutral`. It does not certify the code or the transcript. Repeated
runs update this app's existing check or comment. A human comment or another
app's bot comment cannot select the comment to update.

The required repository permissions for registration are contents read,
pull requests read and checks write. Comment mode also needs issues write. The
webhook subscription is pull requests. No workflow permission or code execution
permission is needed. No registration is performed by the CLI.

## Evidence and reader rules

Commit trailers, ASR VCS records and annotations supply candidate links. A trailer
or annotation alone earns no blame credit. Commit credit needs an original VCS
record, successful recorded status, supported action and evidence, and local
commit checks. An unknown status can use a uniquely paired completed tool result.
A failed status stays failed. Abbreviated IDs also need a unique object match,
exact subject, valid parent shape and local branch or tag reachability.

For edits, the app uses Git blame at the candidate commit and verifies the path
at the introducing commit. It matches original applied file changes against lines
that were actually added. Before and after states, available blob IDs, recorded
patches and replacement snippets supply evidence. Unchanged and dirty context,
file touches without text evidence and ambiguous matches earn no edit credit.
An after-state alone needs an observed add and a file absent from the parent.

Completed rewrite pairs are followed backward only when both objects exist.
Recorded amend boundaries are supported. Commit history carries forward while
edit evidence is checked against surviving successor lines. Single-parent landed
commits include the squash or rebase result itself. Multi-parent merges use
commits reachable from any non-first parent but not the first parent.

Copied records and copied prefixes earn no work credit. Approval records retain
file order and show whether they are copied. Approvals join calls only when the
call ID is unique. Session-wide approvals do not certify a specific commit.
Human edit actors stay labeled as human. External actors earn no edit credit.
The latest surviving edit within a stream is selected with earlier alternatives.
Competing sessions stay unresolved. Served and requested models remain distinct.
Prompts need a recorded turn link and human authorship. No nearby model or prompt
is borrowed to fill missing evidence.

Losses are the union of the header and all later updates. Gaps, truncation and
reader issues are reported. No declared loss does not establish complete capture.
Annotation corrections apply before time selection. VCS facts stay additive.
Parent-side and child-side subagent links are combined without transferring credit.

Malformed complete JSONL lines are reported and skipped. Incomplete tails are
ignored until completed. Duplicate keys and invalid UTF-8 are reported. Numeric
lexemes are preserved exactly in the reader. Unknown records, fields and enum
values remain untrusted data. They do not create attribution evidence.

## Limits and safety

The app reads local ASR files. It does not write or modify ASR. It never runs a
recorded command or fetches a recorded URI. Summary output uses an allowlist of
metadata and escapes untrusted text. Transcript text, patches, commands, tool
arguments, approval subjects, identities and arbitrary annotation text are not
included. Links and metadata can still disclose private work. Enable publication
only for repositories whose audience may see those links and metadata.

The GitHub commit-list endpoint caps results at 250. The app stops at that
boundary rather than treating a truncated list as complete. Unavailable history,
API errors and changed pull requests stop publication. State and replacement
matching deliberately withholds repeated lines and partial replacement blocks
that do not survive uniquely. Some valid edits can remain unresolved. Move and
copy propagation uses recorded order within a session. It does not guess order
between sessions or infer rewrite pairs from similar patches.

The store is limited to 1000 files, 64 MiB per file, 256 MiB total and 16 directory
levels. Git output is limited to 32 MiB per command with a 30 second timeout.
Webhooks are limited to 2 MiB and API responses to 16 MiB. Oversized inputs fail.
GitHub summaries are shortened below 50,000 bytes with an explicit omission
notice. Run the report command to retain the full JSON result.

Delivery IDs are remembered in memory for one day, up to 10,000 entries. Work is
serialized per pull request within one process. API state supplies sequential
retry idempotence after a restart. There is no distributed lock or durable queue.
Run one process. Concurrent deployments can create duplicate summaries. Failed
webhooks return an error and rely on redelivery. No retry scheduler, background
repository refresh, rate-limit queue or hosted store adapter is included.

## Tests

Tests cover the repository samples and examples, exact JSON numbers, framing
recovery, copied credit, approvals, gaps, annotation corrections, local blame,
abbreviated IDs, failed actions, rewritten commits, surviving edits, competing
sessions, literal filenames, squash and multi-parent merges. HTTP tests exercise
signatures, app JWTs, installation token caching, check and comment updates,
pagination, stale heads and the report CLI against a loopback mock. Test data is
synthetic. Temporary repositories, keys, output files and listeners are removed
when each test ends.
