// Generated from spec/conformance.md by scripts/build-requirements.mjs.
export const REQUIREMENTS = {
  "ASR-078": {
    "page": "format",
    "summary": "Stable requirement IDs and meanings with versioned breaking changes",
    "check": "fixture"
  },
  "ASR-001": {
    "page": "format",
    "summary": "UTF-8 JSONL objects, LF framing and unique object keys",
    "check": "semantic"
  },
  "ASR-002": {
    "page": "format",
    "summary": "Exactly one session header on line 1 with version 0.1",
    "check": "semantic"
  },
  "ASR-003": {
    "page": "format",
    "summary": "Completed items in source order, never reordered by time",
    "check": "fixture"
  },
  "ASR-075": {
    "page": "format",
    "summary": "Folded completion positions, receipt order and snapshot approvals",
    "check": "fixture"
  },
  "ASR-077": {
    "page": "format",
    "summary": "String encoding for large native values and exact numeric preservation",
    "check": "fixture"
  },
  "ASR-004": {
    "page": "format",
    "summary": "Live writers append and converters can re-export",
    "check": "fixture"
  },
  "ASR-005": {
    "page": "format",
    "summary": "Recover after malformed lines and defer incomplete tails",
    "check": "fixture"
  },
  "ASR-006": {
    "page": "format",
    "summary": "Common envelope fields and shapes",
    "check": "schema"
  },
  "ASR-007": {
    "page": "format",
    "summary": "Record ID shape and uniqueness",
    "check": "semantic"
  },
  "ASR-008": {
    "page": "format",
    "summary": "Native or deterministic opaque IDs and external citations",
    "check": "fixture"
  },
  "ASR-009": {
    "page": "format",
    "summary": "Source times and explicit live lifecycle receipt times",
    "check": "fixture"
  },
  "ASR-010": {
    "page": "format",
    "summary": "Agent names, native session IDs and installation namespaces",
    "check": "fixture"
  },
  "ASR-011": {
    "page": "format",
    "summary": "Reference grammar, encoding and session-only targets",
    "check": "schema"
  },
  "ASR-012": {
    "page": "format",
    "summary": "Absolute and relative paths, with embedded paths preserved",
    "check": "fixture"
  },
  "ASR-013": {
    "page": "format",
    "summary": "Ordered content parts and part-level overrides",
    "check": "schema"
  },
  "ASR-014": {
    "page": "format",
    "summary": "Exact text and concatenated streaming deltas",
    "check": "fixture"
  },
  "ASR-015": {
    "page": "format",
    "summary": "Reasoning visibility without encrypted content or provider state",
    "check": "fixture"
  },
  "ASR-016": {
    "page": "format",
    "summary": "Preserve unknown data and keep enums open",
    "check": "fixture"
  },
  "ASR-017": {
    "page": "format",
    "summary": "Vendor field, record type, content-part type and enum naming",
    "check": "schema"
  },
  "ASR-018": {
    "page": "format",
    "summary": "Extensions are declared and preserve core meanings",
    "check": "fixture"
  },
  "ASR-019": {
    "page": "records",
    "summary": "Session shape, non-empty sourced identities, authorship limits and repositories",
    "check": "schema"
  },
  "ASR-020": {
    "page": "records",
    "summary": "Session updates, verbatim policies, per-field settings, null clears and whole outer boundaries",
    "check": "fixture"
  },
  "ASR-072": {
    "page": "records",
    "summary": "Asking from recorded policy, invalidation on changes and stated outer boundaries",
    "check": "fixture"
  },
  "ASR-074": {
    "page": "records",
    "summary": "Recorded offered tools, partial-list losses and whole-list replacement",
    "check": "fixture"
  },
  "ASR-021": {
    "page": "records",
    "summary": "Message role, content and optional fields",
    "check": "schema"
  },
  "ASR-022": {
    "page": "records",
    "summary": "Human authorship and compaction summaries",
    "check": "fixture"
  },
  "ASR-023": {
    "page": "records",
    "summary": "Tool call fields and exclusive input forms",
    "check": "schema"
  },
  "ASR-024": {
    "page": "records",
    "summary": "Native call IDs, names, kinds and request authorship",
    "check": "fixture"
  },
  "ASR-025": {
    "page": "records",
    "summary": "Recorded tool outcomes, exit codes and model-facing output",
    "check": "fixture"
  },
  "ASR-076": {
    "page": "records",
    "summary": "Effective tool input learned at completion and exclusive forms",
    "check": "schema"
  },
  "ASR-026": {
    "page": "records",
    "summary": "One result per call ID and pairing only to a unique call",
    "check": "semantic"
  },
  "ASR-079": {
    "page": "records",
    "summary": "Result approval links from stated decisions to a local approval for the same call",
    "check": "semantic"
  },
  "ASR-073": {
    "page": "records",
    "summary": "Approval records, source order, reused grants and real lifetimes",
    "check": "fixture"
  },
  "ASR-027": {
    "page": "records",
    "summary": "File changes, move origins and exclusive edit and actor forms",
    "check": "schema"
  },
  "ASR-028": {
    "page": "records",
    "summary": "Applied changes and observed actors",
    "check": "fixture"
  },
  "ASR-029": {
    "page": "records",
    "summary": "Historical file content and recorded patches",
    "check": "fixture"
  },
  "ASR-030": {
    "page": "records",
    "summary": "File object ID types, lengths and default",
    "check": "schema"
  },
  "ASR-031": {
    "page": "records",
    "summary": "VCS fields, exclusive actors, commit IDs and PR identity",
    "check": "schema"
  },
  "ASR-032": {
    "page": "records",
    "summary": "Parent counts, distinct rewrites and consistent commit lengths",
    "check": "semantic"
  },
  "ASR-033": {
    "page": "records",
    "summary": "Actions and references come from source evidence",
    "check": "fixture"
  },
  "ASR-034": {
    "page": "records",
    "summary": "Model calls come from source boundaries",
    "check": "fixture"
  },
  "ASR-035": {
    "page": "records",
    "summary": "Optional model with declared loss, distinct identities and sourced settings",
    "check": "schema"
  },
  "ASR-036": {
    "page": "records",
    "summary": "Inclusive usage totals and recorded zeros",
    "check": "fixture"
  },
  "ASR-037": {
    "page": "records",
    "summary": "Cost amount, currency and unknown values",
    "check": "schema"
  },
  "ASR-038": {
    "page": "records",
    "summary": "Per-call accounting excludes copies and session totals",
    "check": "fixture"
  },
  "ASR-039": {
    "page": "records",
    "summary": "Gap fields and corrupt-source reporting",
    "check": "fixture"
  },
  "ASR-040": {
    "page": "sessions",
    "summary": "Parent and copy-source shapes",
    "check": "schema"
  },
  "ASR-041": {
    "page": "sessions",
    "summary": "Copied prefix ends at a local record after the header",
    "check": "semantic"
  },
  "ASR-042": {
    "page": "sessions",
    "summary": "Lineage only from native evidence and known copy losses",
    "check": "fixture"
  },
  "ASR-043": {
    "page": "sessions",
    "summary": "Copies receive no credit and new child calls do",
    "check": "fixture"
  },
  "ASR-044": {
    "page": "sessions",
    "summary": "Combine subagent links and allow unavailable sessions",
    "check": "fixture"
  },
  "ASR-045": {
    "page": "sessions",
    "summary": "Stable resume identity and retained native branches",
    "check": "fixture"
  },
  "ASR-046": {
    "page": "code",
    "summary": "Git blame and repository path checks",
    "check": "fixture"
  },
  "ASR-047": {
    "page": "code",
    "summary": "Exact rewrites carry history with surviving edit checks",
    "check": "fixture"
  },
  "ASR-048": {
    "page": "code",
    "summary": "Commit status decides, with fallback only for unknown",
    "check": "fixture"
  },
  "ASR-049": {
    "page": "code",
    "summary": "Verify full commits or every short-ID check",
    "check": "fixture"
  },
  "ASR-050": {
    "page": "code",
    "summary": "Match only edit-added lines and exclude dirty context",
    "check": "fixture"
  },
  "ASR-051": {
    "page": "code",
    "summary": "Surviving edits, alternatives and actor attribution",
    "check": "fixture"
  },
  "ASR-052": {
    "page": "code",
    "summary": "Separate edit and commit credit with recorded model links",
    "check": "fixture"
  },
  "ASR-053": {
    "page": "code",
    "summary": "PR actions and membership for multi- and single-parent merges",
    "check": "fixture"
  },
  "ASR-054": {
    "page": "code",
    "summary": "Trailer and Git AI links require checks",
    "check": "fixture"
  },
  "ASR-055": {
    "page": "missing-data",
    "summary": "Absence is unknown and falsy values are real",
    "check": "fixture"
  },
  "ASR-056": {
    "page": "missing-data",
    "summary": "Do not invent native facts",
    "check": "fixture"
  },
  "ASR-057": {
    "page": "missing-data",
    "summary": "Declare known losses in the header or later updates and keep their union",
    "check": "fixture"
  },
  "ASR-058": {
    "page": "missing-data",
    "summary": "Mark shortened text and missing history",
    "check": "fixture"
  },
  "ASR-059": {
    "page": "missing-data",
    "summary": "Untrusted content without fetching or execution",
    "check": "fixture"
  },
  "ASR-060": {
    "page": "missing-data",
    "summary": "Exclude secrets, identify derived-file producers and link exact source bytes",
    "check": "fixture"
  },
  "ASR-061": {
    "page": "annotations",
    "summary": "Later facts use a separate annotations file",
    "check": "fixture"
  },
  "ASR-062": {
    "page": "annotations",
    "summary": "Annotation identity, target, source and learned time",
    "check": "schema"
  },
  "ASR-063": {
    "page": "annotations",
    "summary": "Kind-specific payloads and open values",
    "check": "schema"
  },
  "ASR-064": {
    "page": "annotations",
    "summary": "Corrections name earlier annotations",
    "check": "semantic"
  },
  "ASR-065": {
    "page": "annotations",
    "summary": "Corrections first, current values by time, additive tests and VCS",
    "check": "fixture"
  },
  "ASR-066": {
    "page": "annotations",
    "summary": "Annotations inform links without granting blame credit",
    "check": "fixture"
  },
  "ASR-067": {
    "page": "conformance",
    "summary": "Writers validate, declare losses and publish mapping samples",
    "check": "fixture"
  },
  "ASR-068": {
    "page": "conformance",
    "summary": "Readers follow interpretation and safety rules",
    "check": "fixture"
  },
  "ASR-069": {
    "page": "conformance",
    "summary": "Validator errors cover structural and relational checks",
    "check": "fixture"
  },
  "ASR-070": {
    "page": "conformance",
    "summary": "Validator warnings cover incomplete and unfamiliar data",
    "check": "fixture"
  },
  "ASR-071": {
    "page": "conformance",
    "summary": "Validation is offline and cannot prove faithfulness",
    "check": "fixture"
  }
};
