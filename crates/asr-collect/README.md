# Session collection

`asr collect` finds native session files, converts changed sessions and stores exact ASR files.
`asr receive` accepts authenticated uploads and writes collection manifests.
Both commands use the repository's Node validator. Run them from the repository or set `ASR_REPO_ROOT`.

## Install

Install the [ASR CLI and validator dependencies](../asr-cli/README.md#install).
The `asr-collect` crate supplies the CLI's `collect` and `receive` subcommands.
It has no separate binary. Use `asr collect --help` and `asr receive --help`
for the complete option lists.

## Collect to a local directory

```sh
asr collect --target ./received --state ./collector-state --uploader configured-account
asr collect --target ./received --state ./collector-state --uploader configured-account --watch
asr collect --source claude-code=./native-history --target ./received --state ./collector-state --uploader configured-account
```

Default roots are `CLAUDE_CONFIG_DIR/projects`, or `.claude/projects` below the home directory,
and `CODEX_HOME/sessions` and `CODEX_HOME/archived_sessions`, or their `.codex` equivalents.
Discovery also includes the native roots for every converter listed by `asr agents`.
The [root table in the source](src/discovery.rs) defines Linux home, XDG and current-project locations.
Use explicit sources for other platforms and installation layouts.
Use `--agent` to restrict default discovery. Use repeated `--source agent=path` arguments for other roots or files.
An explicit unavailable root fails the scan. Missing default roots are skipped.
State and targets must be outside source directories.

The converter framework handles discovery, compressed companions and recorded session identity.
Files for the same recorded session are converted together. A change to one file re-exports that group.
Databases can supply several sessions. Each session gets its own output and checkpoint.
Companion metadata, snapshot components, approval stores and SQLite WAL files participate in change detection.
Set `--namespace` for installation-scoped native IDs. Goose requires it.
Directory-keyed legacy Kiro sessions also require it.
A deleted source is removed from the next group. Stored versions remain available.
Deleting all sources does not delete a collected session.

The state directory retains source metadata, content digests, native identity, completed checkpoints and pending upload IDs.
Unchanged metadata skips native parsing and conversion. Metadata includes change time on Unix.
Changed metadata triggers hashing and identity discovery. A changed group with identical output needs no upload.
Source mutation during discovery or conversion defers the result for retry.
On systems without change time, edits that preserve size and modification time need a fresh state directory.

File events trigger scans in watch mode. A periodic scan also runs to recover missed events.
Use `--poll-only` to disable file events. `--poll-seconds` defaults to 30.
`--max-sessions` bounds changed sessions per scan. `--recent-hours` selects sessions by source modification time.
These options still inventory the configured roots. Use explicit source files to bound the initial inventory.
Related files within the configured roots remain in each selected session's group.

A generated machine ID persists in state. Set `--machine` to use an assigned ID.
A state directory belongs to one machine, target, uploader, source configuration and converter record limit.
Use a different state directory when changing those settings. Run one collector per state directory.
The local target also accepts a `file://` URL.

## Receive uploads

Create an owner-only authentication file containing an array of entries.
Each entry assigns one bearer token to an uploader and its permitted machines.

```json native
[
  {
    "token": "<random-token-at-least-16-characters>",
    "uploader": "configured-account",
    "machines": ["machine-7"]
  }
]
```

```sh
chmod 600 receiver-auth.json collector-token
asr receive --out ./received --auth-file ./receiver-auth.json --bind 127.0.0.1:8787
asr collect --target http://127.0.0.1:8787 --token-file ./collector-token --machine machine-7 --state ./collector-state --watch
```

The collector token file contains only the token. Tokens never appear in command arguments or receipts.
The receiver chooses `uploader` from the authentication entry. A caller cannot override it in an upload.
Plain HTTP collection is limited to loopback. Put a TLS reverse proxy in front of a remote receiver.
Redirects are refused. The receiver is a serial reference service with a configurable upload byte limit.
It relies on the reverse proxy for connection deadlines and request rate limits.
Restart the receiver after changing its authentication file.

The HTTP API uses POST requests. Every request carries `Authorization: Bearer <token>` and `X-ASR-Machine`.
`/v1/heartbeat` registers the machine. `/v1/sessions` accepts the exact file body with `X-ASR-Sha256`
and `X-ASR-Upload-ID`. `/v1/failures` accepts an upload ID and a JSON object with a
`reason` string and an optional session reference in `session`.
A repeated upload ID returns the original receipt. Different bytes or uploader identity for that ID are refused.
The collector saves its pending ID before transfer and reuses it after an interrupted acknowledgement.

## Store files and receipts

Valid files live at `objects/<sha256>.jsonl`. Their digest covers every byte, including newlines.
Unreadable uploads are retained as `objects/<sha256>.bin`. They have a digest, length and reason.
Failed transfers and reported collection failures have a reason without a fabricated digest.
The original session's producer and user stay in its bytes.
When a recorded `user.id` differs from the authenticated uploader, the receipt adds `identityMismatch`
with both identities for review. Directory joins and comparisons of other identity fields belong to company policy.

A private SQLite database retains receipts and version links. It commits receipts before acknowledging them.
Completed manifests are immutable JSON files at `manifests/<machine-digest>/<window-start>.manifest.json`.
Each manifest passes the repository manifest schema. It links the exact preceding manifest bytes.
Each receipt uses the receiver clock and belongs to a window that includes its start and excludes its end.
Re-exports add receipts with `replaces` when the digest changes. Prior receipts remain available.

Windows are fixed UTC intervals. The default is 3600 seconds. Set `--window-seconds` on the receiver,
or on a collector using a direct storage target. Completed windows include empty intervals.
The open window stays in the receipt database until its end. A one-shot collector closes completed windows
on its next run. Watch mode and the receiver close them while running. Restarting also closes elapsed windows.
Empty windows say that nothing arrived. They do not establish that a machine was reachable or had no sessions.
Collection failures appear as failed receipts when the store can be reached.
Session conversion failures name the native session when its identity is known.
Their upload IDs derive from the session and the source content signature.
Repeated scans and collector restarts reuse the receipt for that version.
Changed source bytes get a new failure receipt. Reverting to a previously failed
version reuses its original receipt. Collection still retries transient failures.

Directories have mode 700 on Unix and created data files have mode 600.
Back up the receipt database with the exact files and manifests. Keep the latest manifest digest in protected storage
if tail deletion must be detectable. Retention, signing and write-once policies belong to the store operator.
Local receipt state can recover a manifest file whose database commit preceded its filesystem write.

## Object storage

Direct targets use the `object_store` library's authentication providers and multipart uploads.
They retain a local receipt database under the collector state directory.
They remove the local session copy after the remote upload and receipt commit succeed.
Finished manifests are uploaded after the session files. Failed transfers remain retryable.
Each remote object carries `sha256` metadata. Session keys and manifest contents also identify the digest.
Upload buffering is bounded to one 8 MiB part.

| Target | URL | Configuration |
|---|---|---|
| S3 and compatible services | `s3://bucket/prefix` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, optional `AWS_SESSION_TOKEN`, and `AWS_REGION` |
| S3 endpoint override | Same S3 URL | `AWS_ENDPOINT`, optional `AWS_VIRTUAL_HOSTED_STYLE_REQUEST`, and `AWS_ALLOW_HTTP` for a local test service |
| Google Cloud Storage | `gs://bucket/prefix` | `GOOGLE_SERVICE_ACCOUNT` for a service account file, or `GOOGLE_APPLICATION_CREDENTIALS` for an application credentials file |
| Azure Blob Storage | `az://container/prefix` | `AZURE_STORAGE_ACCOUNT_NAME` and `AZURE_STORAGE_ACCOUNT_KEY`, or the library's service principal and managed identity providers |

Use `--uploader` for direct targets. That identity is configured locally. The HTTP receiver supplies its own authenticated identity.
Do not share a machine's direct target between independent collector states. The local database owns its manifest chain.
GCS and Azure use their library adapters. They have no production service qualification in this package.

## Checks

```sh
cargo test -p asr-collect
cargo build -p asr-cli
python3 crates/asr-collect/scripts/check-local.py --binary target/debug/asr
python3 crates/asr-collect/scripts/check-minio.py --binary target/debug/asr --image LOCAL_MINIO_IMAGE
```

The MinIO check uses a local image, synthetic runtime credentials and a disposable loopback container.
It checks multipart transfer, exact downloaded bytes, digest metadata, receipts and validator results.
It removes the container and credentials on completion. Add `--sudo` when Docker requires it.
CI runs the MinIO check when `ASR_TEST_MINIO_IMAGE` is set. Set `ASR_TEST_DOCKER_SUDO=1` when needed.
The regular Rust tests exercise receipt chains, boundaries, empty windows, retries, failures, identity mismatches,
source grouping and a local authenticated receiver. The CLI checks cover file events, polling and restart.

## Test status and limits

Live-test status: **passed** for local collection, file events, polling,
authenticated receiver requests and multipart uploads to local MinIO.
Production S3, GCS and Azure services were not used. Six bounded local-history
sessions also qualified collection into a private local store. No real session
content is included in the repository.

Collection inherits each converter's source limits. It cannot prove that a
machine exposed every native log or recover events absent from those logs.
Receipts and empty windows describe arrivals. They do not establish complete
capture, machine availability, person identity or authorship. The reference
receiver needs an operator-managed TLS proxy for remote use.
