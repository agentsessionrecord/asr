const object = value => value !== null && typeof value === 'object' && !Array.isArray(value) ? value : {};

function clean(value) {
  if (typeof value === 'string') return value.replace(/\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b/g, '[redacted]');
  if (Array.isArray(value)) return value.map(clean);
  if (value !== null && typeof value === 'object') return Object.fromEntries(Object.entries(value)
    .filter(([key]) => !/^(?:api[_-]?key|authorization|password|access[_-]?token|refresh[_-]?token|credentials|signature|thinkingSignature)$/i.test(key))
    .map(([key, item]) => [key, clean(item)]));
  return value;
}

/** Map the public transcript projection without reading private databases or side stores. */
export function exportTranscript(sessionId, events) {
  if (typeof sessionId !== 'string' || !sessionId) throw new Error('A native session ID is required');
  const inspect = value => {
    if (typeof value === 'number' && (!Number.isFinite(value) || (Number.isInteger(value) && !Number.isSafeInteger(value)))) throw new Error('Unsafe numeric projection cannot be exported losslessly');
    if (value && typeof value === 'object') for (const item of Object.values(value)) inspect(item);
  };
  inspect(events);
  const records = [{ type: 'session', id: 'header', formatVersion: '0.1', agent: { name: 'openclaw' }, sessionId,
    producer: { name: 'openclaw-asr-export', version: '0.1.0', method: 'native', source: 'plugin-sdk-transcript' },
    missing: ['history', 'usage', 'model', 'approvals', 'agent_settings', 'tools', 'file_changes', 'commits', 'subagents', 'copies', 'reasoning', 'media', 'native_metadata', 'message_author', 'timestamps', 'provider_state', 'redacted_fields'],
  }, { type: 'gap', id: 'projection-prefix', reason: 'not_recorded', detail: 'This export covers the retained public transcript projection. Side-store evidence and unavailable history are not read.' }];
  const used = new Set(records.map(record => record.id));
  const results = new Set();
  const append = (record, preferred) => {
    let id = typeof preferred === 'string' && preferred.length && preferred.length <= 240 && !/[\u0000-\u001f\u007f-\u009f]/.test(preferred) ? preferred : `derived-${records.length}`;
    while (used.has(id)) id += '-derived';
    used.add(id);
    records.push({ id, ...record });
  };
  const parts = content => typeof content === 'string' ? [{ type: 'text', text: clean(content) }] : Array.isArray(content) ? content.flatMap(value => {
    const part = object(value);
    return part.type === 'text' && typeof part.text === 'string' ? [{ type: 'text', text: clean(part.text) }] : [];
  }) : [];
  for (const [position, value] of events.entries()) {
    const event = object(value);
    if (event.type === 'session') continue;
    const message = object(event.message);
    const id = event.id ?? `event-${position}`;
    if (event.type !== 'message' || !['user', 'assistant', 'system', 'toolResult'].includes(message.role)) {
      append({ type: 'gap', reason: 'not_recorded', count: 1 }, id);
      continue;
    }
    if (message.role === 'toolResult') {
      if (typeof message.toolCallId !== 'string' || results.has(message.toolCallId)) throw new Error('Tool result identity is absent or repeated in the projection');
      results.add(message.toolCallId);
      const record = { type: 'tool_result', callId: message.toolCallId, status: message.isError === true ? 'failed' : message.isError === false ? 'completed' : 'unknown', content: parts(message.content) };
      if (JSON.stringify(clean(message.content)) !== JSON.stringify(message.content) || (Array.isArray(message.content) && message.content.some(part => object(part).type !== 'text'))) record.truncated = true;
      append(record, id);
      continue;
    }
    const blocks = typeof message.content === 'string' ? [{ type: 'text', text: message.content }] : message.content;
    if (!Array.isArray(blocks)) { append({ type: 'gap', reason: 'unparseable', count: 1 }, id); continue; }
    for (const [index, blockValue] of blocks.entries()) {
      const block = object(blockValue);
      const recordId = index === 0 ? id : `${id}/${index}`;
      if (block.type === 'toolCall' && typeof block.id === 'string' && typeof block.name === 'string') {
        append({ type: 'tool_call', callId: block.id, name: block.name, ...(Object.hasOwn(block, 'arguments') ? { input: clean(block.arguments) } : {}), ...(JSON.stringify(clean(block.arguments)) !== JSON.stringify(block.arguments) ? { truncated: true } : {}) }, recordId);
      } else if (block.type === 'text' && typeof block.text === 'string') {
        append({ type: 'message', role: message.role, content: parts([block]), ...(clean(block.text) !== block.text ? { truncated: true } : {}) }, recordId);
      } else {
        append({ type: 'gap', reason: 'not_recorded', count: 1 }, recordId);
      }
    }
  }
  return records.map(record => JSON.stringify(record)).join('\n') + '\n';
}
