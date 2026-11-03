export default async function install(amp) {
  let record;
  try { ({ record } = await import('../remaining-core/recorder.mjs')); } catch { return; }
  const observe = (event, name, fields = {}) => {
    try { record('amp', { sessionId: event.thread.id, event: name, ...fields }); } catch {}
  };
  amp.on('session.start', event => observe(event, 'session.start'));
  amp.on('agent.start', event => observe(event, 'agent.start', { message: { role: 'user', content: event.message } }));
  amp.on('agent.end', event => observe(event, 'agent.end', { facts: { status: event.status } }));
  amp.on('tool.call', event => {
    observe(event, 'tool.call', { call: true, callId: event.toolUseID, name: event.tool, requestedInput: event.input });
    return { action: 'allow' };
  });
  amp.on('tool.result', event => observe(event, 'tool.result', { callId: event.toolUseID,
    result: { status: { done: 'completed', error: 'failed', cancelled: 'cancelled' }[event.status] || 'unknown',
      input: event.input, ...(event.output !== undefined ? { content: event.output } : {}),
      ...(event.error !== undefined ? { error: event.error } : {}) } }));
}
