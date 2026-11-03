# Conformance fixtures

These cases exercise the validator checks in [Conformance](../spec/conformance.md).
They check structure and local relationships. They do not establish that a writer
faithfully recorded its source, or that a reader assigns blame correctly.

Run the fixtures from the repository root:

```sh
node tools/validator/bin/asr-validate.js conformance conformance/fixtures
node tools/validator/bin/asr-validate.js --json conformance conformance/fixtures
```

Each directory contains one session stream, annotations file or collection
manifest and `expected.json`.
The expected array lists every diagnostic's severity, requirement ID, code, physical
line and JSON pointer. Diagnostic text is for people and is not compared. An empty
array means no diagnostics. Warnings alone pass file validation. A fixture passes
only when its complete diagnostic array matches, including expected errors.
Manifest cases omit requirement IDs because the companion guide adds no requirements.

Malformed complete lines are skipped after an error. An incomplete final line is
not used as a record. Its only diagnostic is a warning. The invalid UTF-8 case
contains a byte that a text editor may replace, so preserve its input bytes.

The unit tests also exercise these cases. The [examples](../examples/README.md)
provide complete, readable sessions and annotations that validate without errors.

## Cases

| Case | Check |
|---|---|
| `minimal` | A header and a message pass. |
| `incomplete-final-line` | An unfinished final record is deferred with a warning. |
| `malformed-middle-line` | A malformed line fails and the next record is still read. |
| `blank-line` | An empty line fails. |
| `duplicate-keys` | Escaped duplicate keys in nested data fail. |
| `invalid-utf8` | Invalid UTF-8 fails without hiding the next record. |
| `header-not-first` | A later header cannot replace line one. |
| `duplicate-header` | A stream has only one header. |
| `unsupported-version` | The declared format version must be supported. |
| `session-shape` | The producer has a method. |
| `session-info-shape` | A session update has a defined update field. |
| `message-shape` | A text part has its text. |
| `tool-call-shape` | A call ID is a string. |
| `tool-result-shape` | A tool result has an outcome. |
| `file-change-shape` | A file path is a plain string. |
| `vcs-shape` | A version control action has evidence. |
| `inference-shape` | A supplied model identifies a served or requested model. |
| `gap-shape` | A missing record count cannot be negative. |
| `duplicate-record-id` | Record IDs are unique across the file. |
| `record-id-shape` | Record IDs have a length limit and exclude control characters. |
| `duplicate-call-id` | Repeated call IDs leave both calls and the result unpaired. |
| `dangling-call` | An unnamed call with no result has two warnings. |
| `unpaired-results` | Unknown and absent call IDs leave results unpaired. |
| `inference-links` | Forward model links resolve and missing model links warn. |
| `commit-shapes` | Full commits and prefixes have distinct lowercase hex shapes. |
| `commit-and-prefix` | A commit ID and its prefix cannot both be present. |
| `file-object-ids` | File hashes follow their declared algorithm and default to SHA-1. |
| `parent-count` | A parent count agrees with the parent array. |
| `rewrite-endpoints` | A rewrite changes the commit ID. |
| `copied-through-invalid` | The copied prefix cannot end at the header. |
| `copies-valid` | A copied prefix and an individual copy can name an unavailable parent. |
| `input-forms` | Tool input uses one representation. |
| `edit-forms` | A file change uses a patch or text edits. |
| `move-origin` | Moving a file names its previous path. |
| `copy-origin` | Copying a file names its source path. |
| `session-reference-shape` | Session references use uppercase escapes and valid UTF-8. |
| `unknown-data` | Unknown fields, parts, enum values and vendor records survive. |
| `annotations-valid` | Known payloads, a correction and an unknown kind pass. |
| `annotation-payload-shapes` | Each known annotation kind requires its payload fields. |
| `annotation-corrections` | Corrections name earlier IDs and cannot name themselves. |
| `annotation-envelope` | Annotation IDs, references and learned times are checked. |
| `annotation-in-session` | Later facts cannot be added to a session stream. |
| `path-and-metadata` | Relative paths use slashes and metadata keys use reverse DNS. |
| `encrypted-reasoning` | Encrypted reasoning carries neither text nor a summary. |
| `duplicate-result` | A call ID cannot have two results, even with different outcomes. |
| `actor-and-call` | File changes and VCS records choose a call or an actor. |
| `annotation-actor-and-call` | VCS annotation payloads enforce the same choice. |
| `session-only-references` | Parent, copy, sender and child session fields exclude fragments. |
| `empty-session-identity` | Session IDs and supplied namespaces are non-empty. |
| `digit-dns-label` | Digit-leading DNS labels and escaped hash characters are accepted. |
| `mixed-commit-lengths` | One VCS record uses one full commit ID length. |
| `annotation-mixed-commit-lengths` | VCS annotation payloads use one full commit ID length. |
| `prefix-without-parents` | A prefix does not require invented parent fields. |
| `user-shape` | An identity source alone does not identify the user. |
| `user-field-types` | User identity fields are strings. |
| `agent-settings-shape` | Agent settings require an object and a string or null mode. Native policies accept any JSON value. |
| `inference-settings-shape` | Model settings have typed values and a non-negative integer token limit. |
| `identity-settings-valid` | Identity sources and settings stay open, with partial updates, zeros and absent values preserved. |
| `person-valid`, `person-shapes` | The same identity shape applies to session users, message senders and approval answerers. |
| `identity-empty-fields` | Supplied identity IDs, email addresses and names are non-empty. |
| `approvals-valid`, `approvals-shapes` | Approval records have a required string decision, optional facts and any native JSON. |
| `approval-disconnect`, `approval-settings-change`, `approval-no-call`, `approval-unpaired` | Decisions survive unfinished calls, span settings changes and can name a subject without a call. Unresolved call IDs warn. |
| `structured-policy-valid` | Native approval and sandbox policies retain objects, arrays, booleans and numbers. Null clears a setting. |
| `asks-valid`, `asks-shapes`, `asks-policy-change` | Asking summaries are optional open strings. A native policy change can omit the summary. |
| `external-sandbox-valid`, `external-sandbox-shapes` | Outer boundaries have optional string kind/source and any native JSON. |
| `configured-model-settings-valid`, `configured-model-settings-shapes` | Configured settings share model-setting types without supplying missing call settings. |
| `derived-from-valid`, `derived-from-shape`, `derived-from-digest` | A source-file link requires a 64-digit lowercase SHA-256. |
| `trigger-shape` | Message origins remain strings. Scheduled and external examples validate. |
| `tools-valid`, `tools-shapes` | Tool lists require names and typed optional descriptions and sources. Empty lists are valid replacements. |
| `live-losses`, `loss-update-shapes` | Later loss updates use arrays of open strings, including empty arrays. |
| `live-completion-input` | Folded completion order, effective result input and explicit live session times. |
| `partial-evidence` | Unknown models, partial tools, cleared settings and copied inference revisions. |
| `missing-model-loss` | An inference without a model requires the model loss declaration. |
| `result-input-forms` | A result cannot supply both argument forms. |
| `settings-clear` | Null clears configured facts, including a whole configured model object. |
| `large-native-values` | Large native identities and arguments stay exact as strings. |
| `manifest-empty`, `manifest-invalid` | Collection windows can be empty, while failed receipts need reasons and links need digests. |
| `manifest-schema-required`, `manifest-schema-version` | A manifest requires the v0 schema URL. |
| `manifest-unknown-status`, `manifest-status-reason` | Unfamiliar statuses warn and require reasons. |
| `manifest-window-order`, `manifest-window-boundaries` | Window order and receipts outside the start-inclusive, end-exclusive interval warn. |

[Reader cases](reader-cases.md) describe attribution and annotation interpretation
checks. They require a reader and repository evidence. The offline validator
checks only structure and local relationships.

Converter checks compare these fields with native samples. Confirm that `user`
comes from an identified source, call settings come from that call or its turn,
and every inference in a turn receives its recorded turn settings. Check that
agent-setting changes produce updates and that unstated defaults remain absent.
The validator cannot establish those source facts from an ASR file alone.

For approvals, compare source decisions and their order, distinguish a fresh
answer from grant reuse, and establish the lifetime before setting `scope`.
For `asks`, compare settings recorded during the session. Do not use
conversion-time config, defaults or tool outcomes. Check that an outer sandbox
encloses the agent process and its work, and that configured model values
are not promoted to call settings. Trigger and person mappings need their own
source evidence. The audit tests also verify the example's redaction link and
manifest digest against exact file bytes.
