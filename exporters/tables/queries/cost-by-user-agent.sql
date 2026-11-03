-- Keep currencies, cost sources and served/requested model identities separate.
-- Sessions.user is a grouping label. It does not identify prompt authors.
-- Session totals do not participate in this query.
SELECT s.user_id, s.user_email, s.agent_name,
       i.model_provider, i.model_id, i.model_requested,
       i.cost_currency, i.cost_source,
       COUNT(*) AS original_calls,
       SUM(i.cost_amount) AS known_cost,
       SUM(CASE WHEN i.cost_amount_text IS NULL THEN 1 ELSE 0 END) AS calls_without_cost,
       SUM(CASE WHEN i.cost_amount_text IS NOT NULL AND i.cost_amount IS NULL
                THEN 1 ELSE 0 END) AS costs_outside_decimal_range,
       SUM(i.input_tokens) AS known_input_tokens,
       SUM(i.output_tokens) AS known_output_tokens,
       SUM(CASE WHEN i.input_tokens IS NULL THEN 1 ELSE 0 END) AS calls_without_input_usage
FROM inferences i JOIN sessions s USING (session_ref)
WHERE i.original = true
GROUP BY s.user_id, s.user_email, s.agent_name,
         i.model_provider, i.model_id, i.model_requested,
         i.cost_currency, i.cost_source;
