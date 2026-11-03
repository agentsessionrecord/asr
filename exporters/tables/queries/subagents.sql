-- Either side can establish a recorded relationship.
-- Unavailable files keep their session references in these edges.
SELECT DISTINCT parent_session, child_session
FROM (
  SELECT l.session_ref AS parent_session, l.target_session AS child_session
  FROM links l JOIN records r USING (session_ref, record_id)
  WHERE l.kind = 'subagent' AND r.original = true
  UNION ALL
  SELECT target_session AS parent_session, session_ref AS child_session
  FROM links WHERE kind = 'parent_subagent'
) relationships;
