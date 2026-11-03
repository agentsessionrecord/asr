# Security and privacy

ASR files can contain private prompts, source code, tool output, paths and identity.
Treat recordings, indexes, exports, receipt stores and backups as private data.
Credential filtering does not make a recording safe to share.

## Report a vulnerability

Email [feedback@agentsessionrecord.org](mailto:feedback@agentsessionrecord.org).
Reports are handled privately. Include the affected tool and version, a description
of the impact, and steps to reproduce the issue. A small synthetic example or
proposed fix can help. Remove credentials and private session content before
sending evidence. Keep vulnerability details out of public issues while the
report is being investigated.

## Trust boundaries

Recorded text, native histories, metadata, paths and URLs are untrusted input.
They can contain instructions, executable text, misleading evidence or large data.
The viewer displays text under a restrictive content security policy.
Readers do not execute recorded commands or fetch recorded URLs.
Forge summaries escape recorded values and omit raw prompts and tool output.
Git reads use argument arrays, literal paths and disabled executable helpers.
They ignore inherited Git routing and configuration variables.

The operator controls configuration, output roots, executables and destinations.
Explicit embedding commands, database loaders, Git note writes, forge publication
and collection uploads use that authority. Review it before enabling those modes.
Plugins run inside trusted agent hosts. This project cannot isolate a malicious
host, a compromised dependency or another process with the same user privileges.

## Capture and storage

Capture filters exclude known credential fields, recognized token syntax and
known credential values. Named values are collected before sibling text is
filtered. Offline converters can also remove later-discovered values from earlier
records. Live capture cannot retract bytes already written before a secret was
identified. Unknown secrets, unusual encodings and private prose can remain.
Rust converters match short secret values only as whole strings to avoid damaging
unrelated source fields. Review recordings before disclosure.

Writers use private files. Collector state, locks and credential files enforce
regular files, ownership, private permissions and a single hard link on Unix.
Collector storage and recorder directories reject symlink components.
Use output roots beneath trusted parents. Path checks do not defend against an
attacker who can replace those parents or act with the recorder's privileges.
Unix permissions do not provide encryption. Protect remote stores and backups
with access control, encryption, retention rules and deletion procedures.

Collectors and receivers preserve uploaded ASR bytes. They do not sanitize an
existing stream. Validation checks format and references, not confidentiality or
the truth of recorded claims. Receipt digests establish byte identity only.

## Resource and network limits

Materializing Python readers cap a file at 64 MiB and 100,000 lines.
Vendor imports cap source bytes at 32 MiB and projected records at 64 MiB.
Shared credential scans cap depth, visited values and retained secret text.
Collector credential files cap reads at 1 MiB. Saved state and manifest reads
cap at 64 MiB.
Forge stores cap files at 64 MiB, total bytes at 256 MiB, files at 1,000 and depth
at 16. The viewer caps selected files at 64 and indexed lines at 250,000.
Allocation can exceed input size. Multiple selected files also add up.
Run untrusted imports under operating system memory, CPU and disk limits.

ACP capture caps frames at 16 MiB, admitted JSON at 64 MiB, observations at
100,000 and sessions at 128. Capture failures stop recording while wire bytes and
the agent's exit code are preserved. Loss records are best effort when storage
fails. Envoy caps buffered bodies at 16 MiB and continues acknowledgments after
capture failures. Offline readers reject capacity excess. Gateway log importers
count skipped input.

Offline tools make no destination requests without an explicit transport mode.
The viewer has no network access. Local loaders disable proxies and redirects.
Forge API clients refuse redirects and cap response bodies at 16 MiB.
Use authenticated collection endpoints and TLS outside trusted loopback links.
Deploy public receivers and webhooks behind request deadlines, concurrency limits,
storage quotas and rate limits. Per-request limits do not bound lifetime storage.
