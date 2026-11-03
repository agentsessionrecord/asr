# Column reference

Schema version 1 uses flat Parquet columns. All columns accept NULL. Strings use
UTF-8. `int64` stores recorded integer counts. `bool` stores true, false or unknown.
`decimal(38,18)` stores exact portable costs with up to 20 integer digits and 18
fractional digits. Each table file includes `asr.tables.version=1` metadata.

## Keys and joins

`sessions.session_ref` is the session key. It includes the agent, optional namespace
and percent-encoded native session ID. Every record table uses
`(session_ref, record_id)` as its key. Every typed record also appears in `records`.
Use `(session_ref, position)` for file order. Positions are physical 1-based lines.
Never join call IDs across sessions. IDs are opaque.

`tool_calls.result_record_id` and `tool_results.paired_call_record_id` contain
only unique pairings. The same rule applies to `paired_call_record_id` on approvals,
file changes and version control actions. Repeated call IDs leave these joins
unresolved. The foreign key to `sessions` always resolves for exported records.
External session and record targets in `links` can remain unresolved.

`links` has one row per recorded edge. The source record and kind identify the
edge together with its target. `diagnostics` is keyed by source index, line and
code. `source_index` is the 1-based input argument index, not a source path.

## Common record columns

All record tables below include these columns. `sessions`, `links` and
`diagnostics` have their own columns.

| Column | Type | Meaning |
|---|---|---|
| `session_ref` | string | Full session reference |
| `record_id` | string | Original opaque record ID |
| `record_ref` | string | Session reference with encoded record fragment |
| `position` | int64 | Physical source line |
| `ts` | string | Source event time, verbatim, when supplied |
| `turn_id` | string | Recorded turn ID |
| `inference_id` | string | Recorded model call reference, possibly forward or unresolved |
| `original` | bool | True when the record receives this session's credit |
| `copied_from_json` | string | Exact-value JSON copy source, when supplied |
| `truncated` | bool | Source truncation flag, without inventing false |

## Sessions

One row per selected session. The final snapshot follows the spec's update rules.
Absent values remain NULL.

| Columns | Type | Meaning |
|---|---|---|
| `session_ref`, `session_id`, `namespace` | string | Full key, native ID and optional native namespace |
| `agent_name`, `agent_version` | string | Recorded agent identity |
| `user_id`, `user_email`, `user_name`, `user_source` | string | Source user label and identity source |
| `producer_name`, `producer_version`, `producer_method`, `producer_source` | string | Software that wrote the ASR source |
| `started_at`, `ended_at` | string | Recorded lifecycle times, with later end updates applied |
| `title`, `cwd` | string | Latest supplied title and starting working directory |
| `parent_session`, `parent_kind` | string | Recorded parent relationship |
| `repos_json` | string | Header and later added repositories, in source order |
| `missing_json` | string | Union of known losses, or NULL if none was supplied |
| `tools_json` | string | Last supplied offered tool list, including an empty list |
| `agent_settings_json` | string | Final settings after merging and clearing facts |
| `latest_usage_json`, `latest_cost_json` | string | Latest original total of each kind, kept separate from calls |
| `includes_subagents` | bool | Scope flag from that latest usage total |
| `source_sha256` | string | SHA-256 of exact source bytes, including an incomplete tail |
| `source_index`, `record_count` | int64 | Input index and accepted record count |

## Records

Common columns plus `record_type` and `raw_json`, both strings. `raw_json` is the
source object without its framing LF. It keeps unknown fields, enums and parts,
whitespace inside the object and numeric spelling. It includes session headers
and unknown record types. Invalid complete lines appear only in diagnostics.

## Messages

Common columns plus string columns `role`, `author`, `origin`, `phase`, `status`,
`from_session`, `person_json` and `content_json`. These map to their ASR fields.
`from_session` maps to `from`. `content_json` preserves ordered parts and their
authorship overrides. No text, edit or authorship is inferred from message content.

## Tool calls

| Extra columns | Type | Meaning |
|---|---|---|
| `call_id`, `name`, `kind`, `requested_by`, `parent_call_id` | string | Recorded call identity, tool and request fields |
| `input_json`, `input_text` | string | Call's original argument representation |
| `locations_json`, `subagent_json` | string | Recorded locations and delegation object |
| `pairing` | string | `paired`, `missing` or `ambiguous` |
| `result_record_id` | string | Unique paired result ID |
| `result_position` | int64 | Paired result's completion position |
| `result_original` | bool | Whether the paired result is original work |
| `outcome` | string | Paired recorded status, otherwise `unknown` |
| `effective_input_json`, `effective_input_text` | string | Result argument override when supplied, otherwise call arguments |
| `result_content_json`, `result_error_json`, `exec_json` | string | Paired model-facing output, error and execution details |
| `duration_ms_text` | string | Exact paired duration as decimal text |

JSON null is the string `null` in `input_json`. Missing input is SQL NULL.
Empty text input is the empty string. These cases remain distinct.

## Tool results

Common columns plus strings `call_id`, `paired_call_record_id`, `pairing`, `status`,
`content_json`, `input_json`, `input_text`, `error_json`, `exec_json`,
`duration_ms_text` and `subagent_json`. Each result has a row, including unpaired
results. `pairing` is `paired` or `unpaired`. Other columns map to recorded result
fields. `duration_ms_text` preserves the exact numeric duration as decimal text.

## Approvals

Common columns plus strings `call_id`, `paired_call_record_id`, `decision`,
`decider`, `scope`, `subject`, `person_json` and `native_json`. `decider` maps to
`by`. Missing deciders stay unknown. Each decision keeps its own record position.

## File changes

Common columns plus strings `call_id`, `paired_call_record_id`, `path`, `old_path`,
`op`, `status`, `actor`, `base_commit`, `before_json`, `after_json`, `patch` and
`edits_json`. These preserve their ASR fields. Paths are never opened or rewritten.
Before and after objects retain their declared hash types and observed text.

## Version control

The file is `vcs.parquet`. Common columns plus strings `call_id`,
`paired_call_record_id`, `action`, `status`, `evidence`, `actor`, `repo`,
`commit_id`, `commit_prefix`, `subject`, `parents_json`, `head_before`, `head_after`,
`rewrites_json`, `branch`, `remote` and `pr_json`, plus integer `parent_count`.
`commit_id` maps to `commit`. Other names map to the corresponding ASR fields.
These are recorded facts. Commit prefixes stay unresolved.

## Inferences

| Extra columns | Type | Meaning |
|---|---|---|
| `model_provider`, `model_id`, `model_requested` | string | Recorded provider, served model and requested alias, kept distinct |
| `settings_json` | string | Only settings recorded for this call |
| `input_tokens`, `cache_read_tokens`, `cache_write_tokens` | int64 | Inclusive input total and its cache components |
| `output_tokens`, `reasoning_tokens` | int64 | Inclusive output total and its reasoning component |
| `cost_amount` | decimal(38,18) | Exact portable cost, or NULL if absent or outside this range |
| `cost_amount_text` | string | Exact source amount as decimal text, also for amounts outside that range |
| `cost_currency`, `cost_source` | string | Recorded currency and cost provenance |
| `stop_reason`, `duration_ms_text`, `error_json` | string | Recorded stop reason, exact duration and error |

Amounts that need rounding or exceed the decimal range get no typed amount.
Their exact value remains available in `cost_amount_text` and `records.raw_json`.
The example cost query counts these cases. Unknown cost remains distinct from a
recorded zero. No cost estimate or model setting is invented.

## Session updates

The file is `session_updates.parquet`. Common columns plus strings `title`,
`ended_at`, `repos_json`, `missing_json`, `tools_json`, `usage_json` and `cost_json`,
boolean `includes_subagents`, and all usage and cost columns from `inferences`.
Each row represents one `session_info`, including updates without totals.
These totals are observations at a position. They are never additive call rows.

## Settings changes

Common columns plus strings `update_json` and `effective_json`. The first preserves
the supplied `agentSettings` patch, including null clears. The second records the
state after applying that patch. Apply it from this position in the stream.
Use the latest preceding settings change for a later action in that session.

## Gaps

Common columns plus strings `reason` and `detail` and integer `count`.
They map directly to the recorded gap. NULL count is unknown. Zero stays zero.
Missing or present gaps do not prove that an event did or did not happen.

## Links

| Column | Type | Meaning |
|---|---|---|
| `session_ref`, `record_id` | string | Source record key |
| `position` | int64 | Source line |
| `kind` | string | `parent_subagent`, `parent_fork`, `parent_continues`, `subagent`, `copied_from`, `message_from` or `inference` |
| `target_session` | string | Recorded target reference, or NULL for an unknown copy source session |
| `target_record` | string | Raw target record ID when supplied |
| `resolved` | bool | Target exists among selected inputs, with inference type checked for inference links |

This table retains evidence from both sides of a relationship. It does not infer
relationships by timing or text similarity. `queries/subagents.sql` combines
parent and child evidence into distinct pairs.

## Diagnostics

Integer `source_index` and `line`, plus strings `code` and `severity`.
Codes are `malformed-line`, `incomplete-tail`, `duplicate-session-skipped` and
`unresolved-copy-boundary`. Severities are `error`, `warning` and `info`.
The table contains no source text or file paths. A recovered malformed line is
still an error in the source. Diagnostics do not claim full schema validation.
