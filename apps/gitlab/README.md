# GitLab merge request session summary

Find ASR evidence behind a merge request and prepare or post a summary comment.
This is integration code. It does not register an application or webhook.

## Install and run

Use Node.js 22.13 or later and the repository's pnpm version. From the repository root:

```sh
pnpm install --frozen-lockfile
node --experimental-strip-types apps/gitlab/cli.ts config.json --offline HEAD
node --experimental-strip-types apps/gitlab/cli.ts config.json --dry-run
node --experimental-strip-types apps/gitlab/cli.ts config.json --post
```

Offline mode reads only local Git and ASR files. Dry run reads the configured GitLab
API and prints a proposed comment. Only `--post` writes a comment. API modes read
the credential from `ASR_GITLAB_TOKEN`. Configure a dedicated account with API access
to the selected project. Keep credentials out of config files and shell history.

```json native
{
  "repo": "/work/project",
  "store": "/work/sessions",
  "repositories": [{"source": "/recorded/project", "local": "/work/project"}],
  "sessionBaseUrl": "https://sessions.example.com/session",
  "apiBase": "https://gitlab.example.com/api/v4",
  "project": "example/project",
  "mergeRequest": 7
}
```

The source root mapping is an explicit operator choice. See the
[Git notes exporter](../../exporters/git-notes/README.md) for repository checks and
attribution limits. Session URLs come from this config. The integration never fetches
URLs from ASR, trailers, notes or API response pagination links.

## Summary behavior

The integration reads merge request metadata and paginated commits from GitLab's REST
API v4. A landed merge with several parents uses commits reachable from the other
parents but not the first. A single-parent squash or rebase merge includes the landed
commit itself. Required commits must already exist locally. No fetch is performed.

Candidate links come from `Agent-Session` trailers, ASR link notes, Git AI notes, VCS
records and annotations. Local surviving edit evidence can find sessions even when
a person committed their edits. Annotations and links alone grant no attribution.
The summary separates edited lines from verified commit credit and shows competing
matches, recorded approvals, declared losses, gaps and unresolved references.

Approval decisions remain decisions. They do not establish execution or success.
Only a unique call ID pairs an approval with a call. Copied approvals do not count as
new decisions. Missing approval history remains unknown. The comment omits message
text, tool input, approval subjects and gap details. Identifiers and labels are escaped
for Markdown and mentions. Review the resulting links and labels before sharing them.

Comments carry a stable marker. Repeated posting updates the authenticated account's
existing comment, or does nothing when its body matches. Other users' comments are
preserved even if they contain the marker. Several owned comments cause an error.
Pagination is bounded and repeated pages fail. Redirects are rejected. API errors
report status codes without printing response bodies or credentials.

This CLI can run in a user-managed CI job or webhook worker. Event authentication,
queueing, application registration and hosting belong to that deployment. The client
uses HTTPS except for loopback HTTP mocks. Hosted GitLab was not live-tested.

## Tests

```sh
bash exporters/git-notes/check.sh
```

The shared check type-checks both tools and runs local Git fixtures, all repository
samples and examples, and a mocked API. Tests do not contact GitLab or post externally.
