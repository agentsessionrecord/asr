const owns = (o, k) => Object.hasOwn(o, k);
const decisions = { allow: 'approved', deny: 'denied', granted: 'approved', denied: 'denied', cancelled: 'cancelled' };
const choose = (object, keys) => Object.fromEntries(keys.filter(key => owns(object, key)).map(key => [key, object[key]]));

export function adapt(agent, payload) {
  const p = payload;
  if (!p || typeof p !== 'object') return undefined;
  if (agent === 'cline') {
    const event = p.hookName;
    const t = p.tool_call || p.tool_result;
    return { sessionId: p.taskId, event, callId: t?.id, name: t?.name,
      call: event === 'tool_call', ...(event === 'tool_call' && t && owns(t, 'input') ? { requestedInput: t.input } : {}),
      ...(event === 'tool_result' ? { result: { status: typeof t?.error === 'string' ? 'failed' : 'unknown',
        ...choose(t, ['input', 'durationMs', 'error']), ...(owns(t, 'output') ? { content: t.output } : {}) } } : {}),
      ...(event === 'prompt_submit' && typeof p.userPromptSubmit?.prompt === 'string' ? { message: { role: 'user', content: p.userPromptSubmit.prompt } } : {}),
      // agent_start/agent_end are runs, not session lifetime boundaries.
      ...(event === 'session_shutdown' ? { facts: { reason: p.reason } } : {}) };
  }
  const grok = agent === 'grok-build';
  const event = p.hook_event_name || p.event;
  const observation = { sessionId: grok ? p.sessionId : p.session_id, event,
    callId: grok ? p.toolUseId : (p.tool_use_id || p.tool_call_id),
    name: grok ? p.toolName : p.tool_name, cwd: grok ? p.cwd : (p.cwd || p.working_dir),
    ...(grok && p.promptId ? { turnId: p.promptId } : p.turn_id ? { turnId: p.turn_id } : {}),
    facts: choose(p, ['decision', 'policy_evaluated', 'blocked_by', 'reason', 'cause', 'source', 'agent_name', 'agent_id', 'agent_type', 'toolInputTruncated']),
    ...(p.toolInputTruncated === true ? { truncated: true } : {}) };
  if (event === 'SessionStart') { observation.start = true; observation.fresh = (p.source || p.startSource) === 'startup'; }
  if (event === 'SessionEnd') observation.end = true;
  if (event === 'PreToolUse') {
    observation.call = true;
    const key = grok ? 'toolInput' : 'tool_input';
    if (owns(p, key)) observation.requestedInput = p[key];
  }
  if (event === 'PreToolUseResult' && agent === 'goose' && (p.decision === 'deny' || (p.decision === 'allow' && p.policy_evaluated && !p.cause))) {
    observation.approval = { decision: decisions[p.decision], by: p.cause === 'hook_failure' ? 'fallback' : 'hook' };
  }
  if (event === 'PermissionResult' && agent === 'crush' && decisions[p.decision]) observation.approval = { decision: decisions[p.decision] };
  if (event === 'PermissionDenied' && grok) observation.approval = { decision: 'denied' };
  if (event === 'PostToolUse' || event === 'PostToolUseFailure') {
    observation.result = { status: event === 'PostToolUseFailure' ? 'failed' : 'completed' };
    // Goose's hooks carry no output at all. DeepSeek's post hook has no outcome flag.
    if (agent === 'goose' || agent === 'mux' || agent === 'deepseek-harness') observation.result.status =
      agent === 'goose' ? (event === 'PostToolUseFailure' ? 'failed' : 'completed') : 'unknown';
    const input = grok ? 'toolInput' : 'tool_input';
    if (owns(p, input) && agent !== 'mux') observation.result.input = p[input];
    const output = grok ? 'toolResult' : agent === 'kimi-code' ? 'tool_output' : 'tool_response';
    if (owns(p, output)) observation.result.content = p[output];
    if (typeof p.error === 'string') observation.result.error = p.error;
  }
  if (event === 'UserPromptSubmit') {
    const content = agent === 'goose' ? p.message : grok ? p.prompt : p.prompt;
    if (typeof content === 'string') observation.message = { role: 'user', content };
  }
  if ((event === 'Stop' || event === 'TurnEnd') && typeof (p.last_assistant_message ?? p.lastAssistantMessage) === 'string') {
    observation.message = { role: 'assistant', content: p.last_assistant_message ?? p.lastAssistantMessage };
  }
  const approval = grok ? p.permissionMode : p.permission_mode;
  if (approval !== undefined) observation.settings = { approval };
  if (agent === 'kimi-code') {
    // 2.x prompts are ordered content parts. Queue/turn events are observations,
    // since replaying their prompt would duplicate UserPromptSubmit.
    if (event === 'UserPromptSubmit' && Array.isArray(p.prompt)) {
      observation.message = { role: 'user', content: p.prompt };
    }
    // Both inspected hosts shorten successful output to 2,000 characters.
    if (typeof p.tool_output === 'string' && p.tool_output.length >= 2000) observation.truncated = true;
    if (event === 'PostToolUseFailure' && p.error && typeof p.error === 'object') {
      observation.result.error = choose(p.error, ['message', 'code']);
    }
    if (event === 'PermissionResult') {
      const decision = { approved: 'approved', rejected: 'denied', cancelled: 'cancelled' }[p.decision];
      if (decision) observation.approval = { decision,
        ...(decision === 'approved' && p.scope === 'session' ? { scope: 'session' } : {}) };
    }
    observation.facts = { ...observation.facts, ...choose(p, ['client_type', 'origin_kind', 'origin_name',
      'scope', 'action', 'prompt_id', 'queue_length', 'task_id', 'description', 'detached', 'uptime_ms',
      'trigger', 'error_type', 'error_message']) };
  }
  return observation;
}
