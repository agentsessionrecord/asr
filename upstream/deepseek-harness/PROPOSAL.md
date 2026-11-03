# DeepSeek harness native Agent Session Record export

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

Adds a native JSON Lines download through the authenticated Host connection. It also exports a pure backend formatter and updates the paired package documentation.

Applies to [https://github.com/deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) at `ce7073d51254c26cd63b22a60835b8f948deb447`. The local patch commit is `2e2c8b883594ea07a8fbef5559917f7a98c5372b`.

Apply the patch with `git am patches/0001-native-agent-session-export.patch` in a clean checkout of that base.

```text
GET /api/session.agent-session?sessionId=SESSION_ID
HEAD /api/session.agent-session?sessionId=SESSION_ID
```

It reads the selected complete committed snapshot with `sessionQuery.readSession`. It records exact text, readable reasoning, instruction messages, model tool calls, final tool results and title observations. The Host route returns a download and never creates a model turn.

Inherited prefixes become a counted gap because original ASR record identities are unavailable. Media, opaque provider state, unknown events, approvals, configured settings and inference accounting are omitted and declared. Unsettled attempts become gaps. The response is buffered in memory. This patch adds a Host route, not a new browser action.

Supported source: Session v4 and the session-query log observation at this revision. Output uses ASR `0.1` and `producer.method: "native"`. File output is exclusive and private where the command writes a file.

Checks: Native formatter test and real Loader composition test passed. 22 focused export and existing Markdown route tests passed. Affected Host project typecheck. Oxlint on all changed TypeScript files. Paired translation check. The included native fixture and sample are synthetic. The sample passes the reference validator with zero errors.

Not live-tested. The available Node runtime is 22.22.2. The project requires Node 24.9 or later for the full application and its native runtime was not built. The real Loader test uses the actual authenticated Host connection and query engine, with an in-memory native session observation.

`manifest.json` pins the upstream base, local commit and packaged file hashes. Run `node upstream/deepseek-harness/check.mjs` from the ASR repository to check this patch package without upstream dependencies.
