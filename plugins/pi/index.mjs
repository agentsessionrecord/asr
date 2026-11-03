export default async function install(pi) {
  let record;
  try { ({ record } = await import('../remaining-core/recorder.mjs')); } catch { return; }
  const inputs = new Map();
  const observe = (event, context, extra = {}) => {
    try {
      const sessionId = context.sessionManager.getSessionId();
      record('pi', { sessionId, event: event.type, cwd: context.cwd, ...extra });
    } catch {}
  };
  pi.on('session_start', (event, context) => observe(event, context, { start: true, fresh: event.reason === 'new' }));
  pi.on('session_shutdown', (event, context) => {
    observe(event, context, { facts: { reason: event.reason } });
    inputs.clear();
  });
  pi.on('session_info_changed', (event, context) => observe(event, context, { title: event.name }));
  pi.on('thinking_level_select', (event, context) => observe(event, context,
    { settings: { modelSettings: { reasoningEffort: event.level } } }));
  pi.on('model_select', (event, context) => observe(event, context, { facts: { requestedModel: event.model?.id } }));
  pi.on('tool_call', (event, context) => observe(event, context, { call: true,
    callId: event.toolCallId, name: event.toolName, parentCallId: event.parentToolCallId, requestedInput: event.input }));
  pi.on('tool_result', (event, context) => {
    // This callback sees execution arguments. Output can still be transformed later.
    if (inputs.size < 4096) inputs.set(event.toolCallId, event.input);
    observe(event, context, { callId: event.toolCallId });
  });
  pi.on('tool_execution_end', (event, context) => {
    const result = { status: event.isError ? 'failed' : 'completed',
      content: event.result?.content, durationMs: event.durationMs };
    if (inputs.has(event.toolCallId)) result.input = inputs.get(event.toolCallId);
    inputs.delete(event.toolCallId);
    observe(event, context, { callId: event.toolCallId, name: event.toolName, result });
  });
  pi.on('message_end', (event, context) => {
    if (!['user', 'assistant'].includes(event.message?.role)) return;
    observe(event, context, { message: { role: event.message.role, content: event.message.content } });
  });
  for (const name of ['agent_start', 'agent_end', 'turn_start', 'turn_end', 'session_compact', 'session_tree', 'ui_prompt_start', 'ui_prompt_end']) {
    pi.on(name, (event, context) => observe(event, context));
  }
}
