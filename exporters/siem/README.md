# ASR SIEM exporter

Convert ASR 0.1 sessions to OCSF 1.4.0 audit events. Write local files for
Splunk HEC, Datadog logs, Elasticsearch or OpenSearch. The exporter does not
send requests. Python 3.11 or later is required. It has no runtime dependencies.

## Install and run

From this directory:

```sh
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/asr-siem ../../examples/approvals-and-policy.jsonl \
  --target elastic --output audit.bulk.ndjson --device-uid example-device
```

You can also run `python3 -m asr_siem` from this directory without installing.
Choose `ocsf`, `splunk`, `datadog` or `elastic` with `--target`.
Use `--index asr-audit` for the Elastic bulk index name.
The CLI creates owner-only files and refuses existing paths.
It also writes `OUTPUT.report.json`. Use `--report PATH` to choose that path.

Records without `ts` stay in the report's `untimed_events`. They have no invented
event time and are excluded from request bodies. If you have a collection
receipt time, supply it with `--observed-at 2026-10-31T00:00:00Z`.
The output marks that time as `explicit_observation` and sets
`metadata.logged_time`. It does not claim the action happened then.
Invalid recorded times stay in the report even with this option.

`--device-uid` names the source device as known to your collector.
It does not name the machine running this exporter unless that machine was the
source. Without it, system records use Base Events and retain the proposed
mapping under `unmapped.asr.system_activity`. A diagnostic identifies the missing
device identity. OCSF requires a device for system events.
File changes by a person, an external actor or an unidentified hook also use
Base Events. The stream does not supply that actor's identity. The exporter
does not substitute the session user or agent as the person who edited a file.

## Mapping

The schema version is pinned to
[OCSF 1.4.0](https://github.com/ocsf/ocsf-schema/tree/6109cc5e834c1adfee67dda6c9bcfa5e37f79012).
`ocsf-pin.json` records source hashes and the field contract checked by tests.
This is a focused mapping contract rather than a full OCSF validator.

| ASR evidence | OCSF mapping | Meaning |
| --- | --- | --- |
| Execute tool request | Process Activity 1007, Launch 1 | Request only, unknown outcome |
| Recorded shell result | Process Activity 1007, Other 99 | Tool result, recorded status and exit code |
| File add, modify, delete, move | File System Activity 1001, 1, 3, 4, 5 | Recorded operation and status |
| File copy | File System Activity 1001, Other 99 | Copy operation retained in ASR metadata |
| Approval | Base Event 0, Other 99, host profile | Authorization result in `actor.authorizations` |
| Recorded network observation | Network Activity 4001 | Recorded connection action and endpoints |
| Recorded HTTP observation | HTTP Activity 4002 | Recorded method, URL and response code |
| Copied record | Base Event 0 | Inherited evidence with `credited: false` |
| Gap, settings and other core records | Base Event 0 | Session context, losses and references |

Authorization events have `metadata.event_code: asr.authorization`.
They preserve `decision`, `by`, `scope` and recorded answerer identity. They use
unknown execution status. OCSF Authorize Session 3003 describes privileges
assigned to login sessions. A tool permission decision does not establish a
login or privilege assignment, so this exporter uses the Base Event class.
Several decisions for one call remain separate events.

Process UIDs start with `asr-command:`. They are deterministic request correlation
IDs made by this exporter, not native process IDs. A command result does not
establish a process termination. A request without a result stays unknown.
Exit codes do not override recorded tool status.

`unmapped.asr` retains source record citations, file position, recorded status,
copy credit, declared losses and relationship information. Unknown enums stay
under that key and use unknown OCSF classifications. No usage or cost totals are
emitted or added. The exporter does not derive blame.

## Recorded network evidence

Core ASR has no structured network observation. A URL in a prompt, a fetch
request or a shell command does not establish network traffic. This exporter
only maps an explicit observation on a `tool_result` under
`_meta.org.agentsessionrecord.siem.network`:

```json native
{
  "observed": true,
  "dst": {"hostname": "example.com", "port": 443},
  "http": {"method": "GET", "url": "https://example.com/resource", "status": 200}
}
```

List `org.agentsessionrecord.siem` in `session.extensions` when producing these
observations. This local exporter contract is not a core ASR extension registry
entry. `src` and `dst` accept recorded `ip`, `hostname` and `port` fields.
At least one endpoint needs an IP or hostname. Without `http`, `activity` can be
`open`, `close`, `reset`, `fail`, `refuse`, `traffic` or `listen`.
Unsupported metadata is ignored. No traffic is inferred from successful tools.

## Content and reader rules

Content is off by default. Prompts, commands, arguments, output, patches, file
contents, approval subjects and gap details are omitted. URL queries, fragments
and credentials are omitted. Paths, endpoint identities, record IDs and recorded
approval answerer identities remain metadata and may still be sensitive.
Settings summaries omit native approval policies and sandbox payloads.

`--include-content` adds selected recorded content and effective tool input.
Recognizable credential patterns and sensitive object keys are masked in both
modes. This is not a complete secret detector. Review content before sharing.
Encrypted reasoning bytes and vendor state are never selected for export.

The reader keeps file order. It reports and skips malformed complete lines and
waits for an incomplete tail. It pairs only a unique call ID, including approvals.
Effective arguments come from a unique result when supplied, including empty
strings and JSON null. Ambiguous and absent references stay visible in the report.
Related sessions are unresolved because this entry point reads one file.
Copied prefixes and individual copies receive no activity or edit credit.
Filter on `unmapped.asr.credited` for session activity counts.
Known losses are the union of all `missing` updates.

Unfamiliar record types are ignored with diagnostics. The original ASR remains
the source of unknown vendor data. This exporter is not an ASR archive.
It preserves exact JSON numbers in selected content. It never runs commands,
loads file paths, or fetches links from the stream. It accepts session streams,
not annotation files. Use the ASR validator separately for full structural checks.

## Request files

- Splunk output is JSON Lines of HEC event envelopes for
  `/services/collector/event`. Each envelope has seconds in `time`, an OCSF object
  in `event`, source `asr` and sourcetype `ocsf:asr`. Add your HEC authorization
  header in your own transport. No credential is written to these files.
- Datadog output is a JSON array for `/api/v2/logs`. Each log has `ddsource`,
  `service`, a fixed summary message, millisecond `timestamp` and nested `ocsf`.
  Configure retention and indexing for the nested fields in your own pipeline.
- Elastic output is Bulk API NDJSON with alternating `index` actions and OCSF
  documents. Stable IDs allow idempotent reloads. Create an ordinary index using
  `elastic-mapping.json`, then submit the file to `/_bulk` with content type
  `application/x-ndjson`. Inspect every item response for errors.

The Elastic mapping disables dynamic indexing and leaves opted-in content in
`_source` without indexing it. Query `metadata.event_code` for event kind and
`unmapped.asr.decision`, `by` and `scope` for approvals. Sort by session reference
and `unmapped.asr.position` to recover file order, including out-of-order times.
The mapping targets regular indices, not data streams.
Batch large request files to the limits of your configured intake.

## Tests

```sh
bash check.sh
ASR_SIEM_OPENSEARCH_URL=http://127.0.0.1:19200 bash check.sh
```

The first command tests all repository ASR samples and session examples,
synthetic edge cases, the reference ASR validator, OCSF field contracts, CLI
permissions and a recorded local HEC request. The OpenSearch test skips when its
URL is absent. It accepts only a loopback HTTP endpoint. It creates a unique
index, loads a bulk request twice, checks approval queries and deletes the index.
Run it against an isolated OpenSearch 2.19.1 container with security disabled and
the HTTP port bound to loopback. Remove that container after testing.

OpenSearch was tested locally. Splunk HEC was tested against a local mock with a
recorded synthetic request. Splunk, Datadog and Elasticsearch services were not
live-tested. No service credentials or accounts are needed for the test suite.
