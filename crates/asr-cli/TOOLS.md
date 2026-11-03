# Redaction, blame and step replay

Install Rust, Git and Node 22 or later. Install the validator dependencies from the
repository root. Keep the validator with the binary, or set `ASR_REPO_ROOT` to its
repository. Each output file passes the Node validator before it is created.

```sh
pnpm --filter @agent-session/validate install --frozen-lockfile
cargo install --path crates/asr-cli --locked
```

All commands print JSON. Successful commands return 0. A failed replay request
returns 1 and saves its failed inference. Other failures return 2. Outputs must be
new files. Output files have owner-only permissions on Unix.

## Redact a file

```sh
asr redact session.jsonl --out shared.jsonl \
  --remove '/user' \
  --remove '/_meta/com.example.agent/private' \
  --mask '/content/*/text'
asr validate --summary shared.jsonl
```

Selectors are JSON pointers relative to each record. Escape `/` as `~1` and `~`
as `~0`. A `*` selects every array item or object field. `--remove` removes selected
fields or array items. `--mask` replaces content strings below a selected value
with `[REDACTED]`. Structural fields such as record IDs, part types, roles and
outcomes stay intact. Binary content becomes an empty base64 string. Tool input
and vendor metadata remain opaque payloads, including their `type` fields.
Masks also follow selected text into payloads and vendor metadata in the same
record, whatever its length. This includes native full file contents, structured
patch lines, tool arguments, result output and strings containing escaped JSON.
Spreading into other records requires the same unique `callId`, at least eight
characters after trimming spaces and at least one letter or number. Multi-line
masks also cover their individual lines. Unrelated records and calls keep their
text. ASR identity and reference fields stay intact.
Repeat either option for more selectors. Removing required fields
fails validation and leaves no output file.

The built-in scan covers provider token prefixes, AWS access key IDs, bearer
values, JWTs, private key blocks, credential assignments, credential object fields
and credentials in HTTP URLs. It scans unknown records and metadata too. Select
fields that contain secret answers or other sensitive values that patterns cannot
identify. Pattern matching does not establish that a file is suitable to share.

The source is preserved. The derived header names `asr-tools` as its producer and
hashes the exact source bytes in `derivedFrom.sha256`. Changed records carry
`truncated: true`. The header keeps inherited losses and adds `redacted_content` when
values changed. Malformed complete lines become gaps. An incomplete final line
is reported and left unread. Unknown fields and exact number tokens are preserved
unless a selected field or secret pattern changes them.

## Find evidence behind a line

```sh
asr blame src/parser.py --line 12 --repo ./project \
  --sessions ./session-store \
  --annotations ./rewrite.annotations.jsonl
```

Repeat `--sessions` for local files or directories. Directory reads do not follow
symlinks. Annotation files are optional and must be supplied explicitly. The
command does not search remote stores or fetch Git objects.

`editedBy` contains matching applied file changes. `committedBy` contains verified
commit actions. Each match has an ASR record citation. Edit matches include the
causing call, recorded human prompt parts, served model or labeled requested
model, and approvals joined only through a unique call ID. Missing links stay
unresolved. Gaps, losses and source parse diagnostics are included. Parent and
subagent links are joined across supplied session files.

The command uses the working tree's Git blame result and its historical path.
Uncommitted lines get no session credit. Recorded repository paths can name the
selected work tree or a directory inside it. If no repository is recorded, a
recorded `cwd` inside that work tree can locate an edit. It does not establish
commit credit. Candidate file paths are resolved relative to the Git root after
normalization. A relocated session store can still be read, but
unavailable recorded repository paths cannot establish attribution.

Commit checks verify full IDs or every abbreviated-ID condition in the spec.
Failed actions remain failed. An unknown action outcome can use only a uniquely
paired completed result. Completed exact rewrites walk backward through existing
Git commits. Rewrite annotations can connect credit but cannot grant it.

Line checks replay recorded replacements, patches and writes in file order on
the introducing commit's first parent. The complete change hunk must match the
commit exactly. A hunk is a contiguous group of added and removed lines. If a
person changes any part of that group that the replay cannot explain, every line
in that hunk stays unknown. Separate hunks can still match.

An edit must fall after the previous commit that changed the path and before the
introducing commit, using Git author dates. Amend, rebase and cherry-pick preserve
that date. The two seconds on either side of a boundary stay unknown. Recorded
full contents and new files need the same timing check. Exact rewrite pairs use
the original commit's window for surviving lines. Without a timestamp, original
commit evidence must bracket the edit in file order. A recorded `baseCommit`
equal to the parent can establish the lower boundary.

Timing uses recorded clocks and Git dates. An additional check needs no clock:
a session cannot receive credit for text already in its first recorded view of
the file. Read output, original contents and the first edit's old text supply
that view. Missing or contradictory evidence stays unknown.

Claude Code structured patch positions, old lines, new lines and context must
agree with the replay. A replacement without recorded original contents or native
hunk context must replace complete lines, including the final newline, at one
unique position. Partial replacements without that evidence stay unknown. A
confirmed new file can use its after state. Blob object IDs are resolved locally.
A plain after state, file touch, trailer, branch or commit association supplies
no edit credit by itself.

Later applied edits in the same stream must preserve the line through the
commit. Potential removals in every supplied session are checked too, including
subagents without a parent-side link. Independent clocks cannot order a possible
removal safely. If native relationship evidence does not establish that it came
before the candidate, the line stays unknown. This can also withhold credit when
an unrelated earlier or later session changed the same path.

Gaps, ambiguous old text, repeated lines, renames with edits and unexplained
formatting can prevent credit. A later re-add loses the earlier origin. The
latest surviving match in a stream wins, with earlier matches in `alternatives`.
Recorded fork and delegation boundaries can order independent streams. Competing
matches without an established order stay unresolved. Human edits receive person
credit. External edits stay untracked.

A matched line means the committed line equals text the session wrote in that
time window. It does not prove who typed it. A person who independently types the
same change or shared new-file boilerplate looks the same in the record.

## Re-ask one model call

Replay reads one explicit private provider settings file. There is no default
endpoint or environment credential fallback. Set an endpoint that you are allowed
to send the source data to. HTTPS is required except for numeric loopback HTTP
hosts. Redirects and environment HTTP proxies are disabled.

For an OpenAI-compatible or Anthropic-compatible endpoint, create this file
with mode 600 and fill its key privately.
Use the endpoint that issued the key in the same settings file.

```json native
{"protocol":"openai","baseUrl":"http://127.0.0.1:PORT/v1","apiKey":"<private-key>"}
```

```sh
chmod 600 provider.json
asr replay session.jsonl --inference inference-7 \
  --provider-settings provider.json --out replay-1.jsonl \
  --model replacement-model --system-prompt-file system.txt \
  --setting temperature=0 --setting maxOutputTokens=512 \
  --variant short-system --run-number 1
```

Use `protocol: "anthropic"` for the Messages API. `baseUrl` is the prefix before
`/messages` or `/chat/completions`, usually ending in `/v1`. A key may be omitted
for a local test endpoint. The file must remain private even when it has no key.
The OpenAI mapping follows the [Chat Completions API reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).

`--setting` accepts the four ASR inference settings as JSON values. A JSON `null`
removes a setting. The command uses call settings, never configured defaults from
`agentSettings.modelSettings`. Anthropic requires `maxOutputTokens` to be recorded
or supplied explicitly. `reasoningEffort` maps to OpenAI `reasoning_effort` or
Anthropic `output_config.effort`. Endpoints can reject settings that their models
do not support.

The request contains text messages, recorded tool requests and uniquely paired
results before the selected inference. Effective arguments learned on a result
override the call's input. The tool list comes from the last earlier `tools`
update. When outputs name the inference, context stops before the first linked
output or the inference record, whichever comes first. Without those links,
context stops before the first assistant message or model-requested tool call
after the previous inference. Inputs before that output remain available.
This conservative boundary can discard useful context. The run declares
`replay_unlinked_outputs`, and the report sets `unlinkedOutputs: true`.
A historical tool call without a
unique earlier result prevents the request. No recorded command or returned tool
call is executed. Resource links are never fetched. Unsupported content parts and
role conversions are declared as losses.

Replay reconstructs context. It does not claim to recover exact model input.
Compaction, gaps and abandoned branches can make it differ from the original.
Each invocation writes a new fork session with copied history marked per record.
Variant and run number are recorded under `org.agentsessionrecord.tools`.
Source directory and repository facts stay under `sourceContext` in that metadata.
They do not claim that replay checked out the recorded starting commit. New
model usage is separate from inherited usage. Anthropic input totals include cache
reads and writes. Cost stays unknown. Tool requests have no result because this
command stops after the next model action. The validator warns about those calls.

HTTP, connection and malformed response failures are recorded as failed inferences.
Error response bodies and credentials are not retained. Known secret patterns and
the configured key are masked in requests and saved run records. Changes to
required structural values can prevent a valid output. Provider signatures and
opaque reasoning state are excluded. Masked replay content declares
`redacted_content` in the session losses.

## Checks

```sh
cargo test -p asr-cli
node tools/validator/bin/asr-validate.js --summary crates/asr-cli/tests/fixtures
```

Tests use local Git repositories, synthetic HTTP responses and every ASR session
under `samples/` and `examples/`. The supported response fixtures cover OpenAI
Chat Completions and Anthropic Messages with the `2023-06-01` API version header.
`live-test.json` records counts and result codes for compatible endpoint checks. Raw model
responses and credentials are not committed. Native-shaped regression tests cover
later person edits, mixed commits, nearby patches, formatter changes, timing
boundaries, session undos, file recreation and related mask copies.

The optional private replay samples a bounded set of local Claude Code Edit
results. Edits with recorded full contents use those contents. Edits without them
use a controlled scratch baseline containing their recorded patch context at
its recorded line positions, while the converted edit keeps `originalFile: null`.
The harness retains native timestamps and structured patches. Scratch commit
times bracket the sampled edits. Edits without usable times or context are skipped. It also checks later person edits.
Only aggregate counts and validator codes leave the temporary directory. This
measures replay behavior on recorded edit shapes rather than actual repository
authorship. No model requests are made.

The optional live check uses temporary private settings and synthetic prompts.
Supply an explicit loopback endpoint and model. For Anthropic Messages, use
`--anthropic-base-url` and `--anthropic-model` instead.
Remove temporary output after reviewing it.

```sh
python3 crates/asr-cli/scripts/live_replay.py \
  --key-file /private/provider-key --openai-base-url "$ASR_OPENAI_BASE_URL" --openai-model "$ASR_OPENAI_MODEL" \
  --out /private/live-result.json
```

Each input is limited to 256 MiB and each line or response to 16 MiB. This version
implements step replay. It does not rebuild a sandbox or run a whole agent task.
