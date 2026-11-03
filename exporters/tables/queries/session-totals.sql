-- Inspect the latest total separately for each session.
-- Never sum these rows across a parent/child tree. True or unknown scope
-- can already include child usage. Per-call accounting uses inferences.
SELECT session_ref, parent_session, parent_kind, includes_subagents,
       latest_usage_json, latest_cost_json, missing_json
FROM sessions;
