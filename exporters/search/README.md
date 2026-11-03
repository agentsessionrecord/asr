# ASR search export

Export Agent Session Record 0.1 streams to OpenSearch bulk JSON and vector chunks.
The Python 3.11 CLI has no runtime dependencies.
OpenSearch 2.19.4 and Qdrant 1.15.5 are tested with local containers.
The bulk mapping uses Elasticsearch APIs, but Elasticsearch has not been live-tested.

## Install and export

From the repository root:

```sh
python3 -m pip install ./exporters/search
asr-search export examples/coding-session.jsonl --output /tmp/asr-search-bundle
```

The source checkout also runs without installation:

```sh
PYTHONPATH=exporters/search python3 -m asr_search export \
  examples/subagent/parent.jsonl examples/subagent/child.jsonl \
  --index asr-records --output /tmp/asr-related-bundle
```

Pass explicit stream filenames. Choose one snapshot per session identity.
Alternate exports of the same session are rejected in one bundle.
Annotation files have a separate format and are outside this exporter's scope.

The output directory must be new. It has owner-only permissions.
Export writes a temporary sibling directory and renames it after completion.
Input files are read twice and their hashes must agree.
The first pass collects record identities and session relationships.
The second pass projects one session at a time.
Memory use includes one session, its documents, a collection-wide identity catalog
and one embedding batch of up to 64 chunks.

## Bundle files

| File | Contents |
|---|---|
| `mapping.json` | Explicit mapping with dynamic fields disabled by a strict schema |
| `documents.jsonl` | One search document per accepted record, including the header |
| `bulk.ndjson` | Alternating index actions and documents, with a final LF |
| `chunks.jsonl` | Ordered text chunks with citations, offsets and optional vectors |
| `manifest.json` | Counts, input hashes, reader diagnostics and output file hashes |

Each search document has a deterministic SHA-256 `document_id`, `session_ref`,
record `citation`, `record_id`, `record_type`, original line `position` and
`source_sha256`. Citations use the spec's percent encoding.
Sort one session's records by `position` to recover file order.
Timestamps are optional search fields and do not set that order.

The original JSON line is retained in `raw_json`, including exact number spelling,
unknown fields, unknown records and unknown content parts.
That field is stored without being indexed.
Large native values and precise decimals avoid a binary float conversion.
Known searchable text appears in `text` and in ordered `text_fields`.
Unfamiliar content parts stay in the raw record and produce no chunks.
Reasoning marked encrypted produces no searchable text.
Embedded resource text is indexed from the stream without opening its URI.
Images, audio and base64 blobs produce no text chunks.

| Search fields | Meaning |
|---|---|
| `agent`, `session_ref`, `record_type` | Exact session and record filters |
| `role`, `author`, `origin` | Recorded message labels, with no inferred authorship |
| `tool_name`, `tool_kind`, `call_id` | Tool request filters |
| `paired_call`, `paired_result`, `pairing` | Conservative joins within one session |
| `call_outcome`, `status` | Call outcome and recorded status |
| `effective_input_json` | Request input, overridden by a uniquely paired result's supplied input |
| `paths`, `resolved_paths` | Explicit recorded paths and lexical resolution against recorded cwd |
| `commits`, `commit_prefix`, `action`, `evidence` | Recorded VCS candidates and evidence labels |
| `model_served`, `model_requested`, `model_provider` | Distinct recorded model values |
| `usage`, `cost_json` | Recorded per-inference figures |
| `copied`, `credit_eligible` | Copy status and eligibility under the copy rule |
| `known_missing`, `unresolved_refs` | Union of declared losses and unresolved joins |
| `gap_reason`, `gap_count` | A gap's recorded reason and optional count |
| `reader_issues`, `gap_records` | Header document's read diagnostics and gap count |
| `relationships`, `related_refs` | Combined parent-side and child-side relationships |
| `agent_settings_json` | Recorded settings in effect before this record |
| `final_agent_settings_json` | Header document's final settings snapshot |
| `session_usage_json`, `session_cost_json`, `session_tools_json` | Latest recorded session totals and offered tool list |
| `current_title`, `current_endedAt`, `repos_json` | Header document's updated session facts |

Path resolution is lexical. It neither opens files nor verifies repositories.
Only explicit paths in repository lists, tool locations, file changes and VCS
records supply path filters. Text mentions remain searchable text.
Commit and file matches are candidates for further checks.
This exporter does not derive edited-by or committed-by attribution.

## Reader behavior

Calls join to results only when there is exactly one call with the ID in that file
and exactly one result. Several results with the same call ID prevent a result join.
Approvals join only to a unique call.
An absent result leaves the call outcome unknown.
An exit code never supplies a status or an approval decision.
The result's supplied effective input can be an empty string or JSON null.
Missing fields stay absent and recorded zero, false and empty values stay present.

Copied prefixes follow file order through `parent.copiedThrough`.
Individual copies follow `copiedFrom`, even when their source is unavailable.
Copies stay searchable and have `credit_eligible: false`.
An unresolved copied-prefix boundary stops export to avoid assigning credit.
Original new inferences in children retain credit.
For usage, filter `record_type: inference` and `credit_eligible: true`.
Sum only the per-call figures you have.
Session totals are stored separately and are never added to per-call usage or
other session totals. Unknown usage and cost remain unknown.

Loss updates are unioned with the header's losses.
Settings updates retain omitted fields, clear null fields and replace an outer
sandbox object as a whole. A mode or policy change without `asks` clears it.
Configured model settings are kept separate from inference settings.
The offered tool list replaces the earlier list as a whole.
Related session files can be unavailable.
Their references remain visible as unresolved.

Malformed complete lines are reported by position and code, skipped, and followed
by normal reading. Invalid UTF-8, duplicate JSON keys, duplicate record IDs and
invalid shapes needed by the reader are reported the same way.
A nonempty final line without LF is deferred and reported as `incomplete_tail`.
Lines over 16 MiB are skipped with a diagnostic while reading continues.
A valid first header and supported format version are required.
Reader diagnostics accompany every affected session in the manifest and header
document. They are separate from recorded gap documents.
The CLI prints counts and diagnostic codes without source text.

## Load OpenSearch

```sh
asr-search load-search /tmp/asr-search-bundle \
  --endpoint http://127.0.0.1:9200 --batch-size 200
```

The loader verifies the bundle hashes and creates the declared index if absent.
An existing index must have the expected mapping.
It sends bounded batches with at most 5 MiB each, checks every item response and
refreshes the index after completion.
A single document exceeding that bound stops loading.
Documents use deterministic IDs, so loading the same bundle again is idempotent.
A failed load can leave completed batches in the index and can be retried.
Use a new index for a changed export that removes records.
The loader upserts documents and does not remove stale records.

The bulk file also follows the standard `/_bulk` request format.
It embeds the index name chosen with `export --index`.

Example requests for a local endpoint:

```jsonl native
{"query":{"match":{"text":"empty input"}}}
{"query":{"term":{"resolved_paths":"/work/app/src/parser.py"}}}
{"query":{"term":{"commits":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}}
{"query":{"term":{"record_type":"gap"}}}
{"query":{"bool":{"filter":[{"term":{"session_ref":"com.example.agent:session-7"}}]}},"sort":[{"position":"asc"}]}
```

## Generate vectors and load Qdrant

Use an explicit local embedding program. There is no default model or hosted
embedding endpoint. The program receives one JSON object on stdin:

```json native
{"texts":["first chunk","second chunk"]}
```

It returns one vector per input, in the same order:

```json native
{"vectors":[[0.2,0.4,0.8],[0.3,0.5,0.7]]}
```

Supply the program as an argv array. It is executed directly without a shell.
Each batch has a 60 second timeout.
Failed commands, wrong vector counts, wrong dimensions and nonfinite values
stop export. Command output is kept out of diagnostics.
The command is configured by the operator and never read from stream content.
Its argv is excluded from the bundle.

The included test program makes synthetic vectors for testing the loader.
These vectors have no useful semantic similarity:

```sh
asr-search export examples/coding-session.jsonl --output /tmp/asr-vector-bundle \
  --embedding-command-json '["python3","exporters/search/tests/fixture_embedder.py"]' \
  --dimensions 3 --embedding-model synthetic-counts-v1
asr-search load-qdrant /tmp/asr-vector-bundle \
  --endpoint http://127.0.0.1:6333 --collection asr-chunks
```

Chunks use Unicode character offsets `[start, end)` into one recorded text field.
They keep content-part order and never cross part boundaries.
Part-level author and origin labels override message-level labels.
Default chunk size is 1200 characters with 100 characters of overlap.
Empty text remains in search documents and produces no vector chunk.
Deterministic UUIDs include the citation, field, chunk configuration, offset and
text digest. The payload carries copy credit, losses, unresolved references,
paths and commits. Every vector carries the configured embedding model label.
Store related streams together to resolve their relationships in the export.

Qdrant collections use unnamed vectors with cosine distance.
Existing vector size and distance must match.
Upserts use `wait=true` and batches of 64 points by default.
Use a fresh collection for changed text or chunk settings that remove chunks.
The loader upserts points and does not delete old chunks.
Without an embedding command, chunks are still exported for another vector store
or a later local embedding stage. The Qdrant loader requires embedded chunks.

## Local handling and limits

Use reviewed and redacted inputs. Raw JSON, prompts, patches and tool arguments
remain in the bundle. The exporter retains recorded data and is not a redactor.
Successful validation establishes structure, without granting permission to share.
Recorded URIs and commands are treated as data.
Only the explicitly configured embedding program is executed.
Only the explicitly supplied database endpoint receives load requests.
Load endpoints must use loopback addresses or localhost.
HTTP proxies are bypassed, redirects are rejected and URL credentials are rejected.
Remote endpoints and authentication are outside these local loaders' scope.
Production embedding model choice, access control, redaction and index retention
belong to the operator.

## Tests

Install the repository's Node dependencies for fixture validation:

```sh
pnpm install --frozen-lockfile
bash exporters/search/check.sh
python3 exporters/search/tests/live.py
```

The focused suite validates and exports all stream samples and examples plus
synthetic fixtures. It exercises malformed lines, incomplete tails, exact numbers,
ambiguous call IDs, missing results, copied credit, settings changes, chunks,
embedding failures and partial bulk failures.
The fixture's unknown extension and vendor record produce two validator warnings.
They test raw preservation and are expected.
Existing samples also contain preserved vendor records and a call without a tool
name. Across the 17 stream inputs, validation reports zero errors and 24 warnings.
Those are 21 unknown types, two unknown extensions and one missing tool name.
No ASR output stream is written by this exporter.

The live harness starts pinned OpenSearch and Qdrant containers on random loopback
ports and removes those containers afterward.
It loads all stream samples and examples, checks text, path, commit and loss
queries, repeats loads, queries vectors and verifies exact raw JSON retention.
Alternate example snapshots use separate indexes and collections.
Set `ASR_SEARCH_DOCKER_JSON` to a JSON argv array if Docker needs a wrapper.
All fixtures and test vectors are synthetic.
