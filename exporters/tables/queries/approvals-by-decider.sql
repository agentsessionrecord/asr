-- Missing deciders remain NULL. Approval is not evidence of execution.
SELECT decider, person_json, decision, scope, COUNT(*) AS decisions
FROM approvals
WHERE original = true
GROUP BY decider, person_json, decision, scope;
