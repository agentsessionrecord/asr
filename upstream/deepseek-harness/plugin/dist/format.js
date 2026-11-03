/**
 * Export original events in source order without loading an Agent or provider.
 * @param session - Header from the same query observation as the events.
 * @param events - Complete validated logical log, including inherited events.
 * @param inheritedEventCount - Number of copied prefix events to exclude from credit.
 * @returns One complete ASR JSON Lines stream.
 */
export function formatAgentSession(session, events, inheritedEventCount) {
    if (!session.id || !Number.isSafeInteger(inheritedEventCount)
        || inheritedEventCount < 0 || inheritedEventCount > events.length) {
        throw new Error('Invalid Session observation');
    }
    const header = {
        type: 'session', id: 'header', formatVersion: '0.1',
        agent: { name: 'deepseek-harness' }, sessionId: session.id,
        producer: { name: 'dsh-plugin-asr-export', version: '1', method: 'native', source: 'session-query-log' },
        missing: ['copies', 'usage', 'model', 'approvals', 'agent_settings', 'tools',
            'file_changes', 'commits', 'subagents', 'media', 'native_events', 'message_author', 'reasoning', 'tool_result_updates'],
    };
    const rows = [header];
    if (session.cwd !== undefined)
        header['cwd'] = session.cwd;
    const startedAt = timestamp(session.createdAt);
    if (startedAt !== undefined)
        header['startedAt'] = startedAt;
    if (inheritedEventCount > 0)
        rows.push({
            type: 'gap', id: 'inherited', reason: 'not_recorded', count: inheritedEventCount,
            detail: 'Fork-inherited events are excluded because their original ASR record identities are unavailable.',
        });
    const results = new Map();
    for (const event of events.slice(inheritedEventCount)) {
        let row;
        switch (event.type) {
            case 'user/message':
                row = { type: 'message', role: 'user', content: parts(event.data.content) };
                if (event.data.source.kind !== 'user')
                    Object.assign(row, { author: 'harness', origin: 'injected' });
                break;
            case 'system/message':
            case 'developer/message':
                row = { type: 'message', role: event.data.message.role, author: 'harness', origin: 'instructions',
                    content: parts(event.data.message.content) };
                break;
            case 'assistant/message':
                row = { type: 'message', role: 'assistant', author: 'model', content: parts(event.data.message.content) };
                if (event.data.interrupted)
                    row['truncated'] = true;
                break;
            case 'tool/call':
                row = { type: 'tool_call', callId: event.data.callId, name: event.data.name,
                    ...argumentsValue(event.data.arguments), requestedBy: 'model' };
                break;
            case 'tool/result': {
                const message = event.data.message;
                const callId = message.source.callId;
                const previous = results.get(callId);
                if (previous !== undefined)
                    rows[previous] = undefined;
                results.set(callId, rows.length);
                row = { type: 'tool_result', callId, status: message.isError ? 'failed' : 'completed', content: parts(message.content) };
                break;
            }
            case 'assistant/attempt':
                row = { type: 'gap', reason: 'not_recorded', detail: 'An unsettled model attempt is not normalized.' };
                break;
            case 'session/title':
                row = { type: 'session_info', title: event.data.title };
                break;
            default:
                // SessionEventMap is merge-extensible. Unknown event payloads stay private.
                break;
        }
        if (row !== undefined) {
            const content = event.type === 'user/message' ? event.data.content
                : event.type === 'assistant/message' || event.type === 'system/message' || event.type === 'developer/message' || event.type === 'tool/result'
                    ? event.data.message.content : undefined;
            if (content?.some(part => part.type !== 'text' && part.type !== 'reasoning'))
                row['truncated'] = true;
            row['id'] = `event-${event.seq}`;
            const ts = timestamp(event.time);
            if (ts !== undefined)
                row['ts'] = ts;
            rows.push(row);
        }
    }
    return `${rows.filter(row => row !== undefined).map(row => JSON.stringify(row)).join('\n')}\n`;
}
function argumentsValue(text) {
    try {
        const input = JSON.parse(text, (_key, value, context) => {
            if (typeof value === 'number' && Number.isInteger(value) && !Number.isSafeInteger(value)) {
                if (context === undefined)
                    throw new Error('Lossless JSON parsing is unavailable');
                return context.source;
            }
            return value;
        });
        return { input };
    }
    catch {
        return { inputText: text };
    }
}
function parts(content) {
    return content.flatMap((part) => {
        if (part.type === 'text')
            return [{ type: 'text', text: part.text }];
        if (part.type === 'reasoning')
            return [asrReasoning(part.text, false)];
        return [];
    });
}
function timestamp(value) {
    if (!Number.isSafeInteger(value))
        return undefined;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? undefined : date.toISOString();
}
function asrReasoning(text, summary = false) {
    if (typeof text !== "string" || text.length === 0)
        return { type: "reasoning", visibility: "omitted" };
    if (summary)
        return { type: "reasoning", visibility: "summary", summary: [text] };
    return { type: "reasoning", text };
}
