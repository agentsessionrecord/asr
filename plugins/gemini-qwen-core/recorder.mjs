import { createHash } from 'node:crypto';
import { isAbsolute, join } from 'node:path';
import { environmentSecrets, credentialValues, isSecretKey, isOpaqueKey, redactSecrets } from '@agent-session/writer';
import { captureSession, HOOK_CONVENTIONS, reasoningPart, markAgentLoss } from '@agent-session/writer/capture';
import { deriveId } from '@agent-session/writer';

export const META = HOOK_CONVENTIONS.metadata;
const MAX_STATE = 2 * 1024 * 1024;
const MAX_PREAMBLE_EVENTS = 8;
const MAX_PREAMBLE_BYTES = 64 * 1024;
const own = (value, key) => Object.hasOwn(value, key);
const object = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const nativeId = (value) => typeof value === 'string' && value.length > 0 ? value : undefined;

export function parsePayload(text) {
  return JSON.parse(text, (key, value, context) =>
    typeof value === 'number' && Math.abs(value) > Number.MAX_SAFE_INTEGER ? context.source : value);
}

function sanitize(value, secrets, flags, depth = 0) {
  if (depth === 0) secrets = [...secrets, ...credentialValues(value)];
  if (depth > 40) { flags.changed = true; return '[omitted]'; }
  if (typeof value === 'string') {
    let clean = redactSecrets(value, secrets);
    if (clean.length > 65536) clean = clean.slice(0, 65536);
    if (clean !== value) flags.changed = true;
    return clean;
  }
  if (Array.isArray(value)) return value.map((item) => sanitize(item, secrets, flags, depth + 1));
  if (!object(value)) return value;
  return Object.fromEntries(Object.entries(value).flatMap(([key, item]) => {
    if (redactSecrets(key, secrets) !== key) { flags.changed = true; return []; }
    if (isSecretKey(key) || isOpaqueKey(key)) {
      flags.changed = true;
      return [[key, '[omitted]']];
    }
    if (['inlineData', 'fileData'].includes(key)) {
      flags.changed = true;
      return [[key, { ...(typeof item?.mimeType === 'string' ? { mimeType: item.mimeType } : {}) }]];
    }
    const clean = sanitize(item, secrets, flags, depth + 1);
    if (/^(?:session_id|tool_use_id|tool_call_id|prompt_id|agent_id|message_id)$/.test(key) && clean !== item) throw new Error('Secret-valued native identity');
    return [[key, clean]];
  }));
}

function parts(value) {
  if (typeof value === 'string') return [{ type: 'text', text: value }];
  if (value === undefined) return undefined;
  return (Array.isArray(value) ? value : [value]).map((part) => {
    if (object(part) && part.thought === true) return reasoningPart(part.text, 'summary');
    if (object(part) && typeof part.text === 'string') {
      return { type: 'text', text: part.text };
    }
    return { type: `${META}/content`, _meta: { [META]: { native: part } } };
  });
}

function project(agent, payload, state, ts, full, flags) {
  const records = [];
  const event = payload.hook_event_name;
  const emit = (type, fields = {}) => {
    const row = { type, ...fields, ts };
    if (nativeId(payload.prompt_id)) row.turnId = payload.prompt_id;
    if (flags.changed) row.truncated = true;
    records.push(row);
    return row;
  };
  const meta = { event, observation: state.observation };
  for (const key of ['timestamp', 'tool_name', 'tool_use_id', 'tool_call_id', 'agent_id', 'source', 'reason', 'agent_type', 'source_type', 'source_id']) {
    if (own(payload, key)) meta[key] = payload[key];
  }
  if (full) {
    for (const key of ['tool_input', 'permission_suggestions', 'original_request_name', 'trigger', 'model', 'message', 'notification_type']) {
      if (own(payload, key)) meta[key] = payload[key];
    }
  }
  emit(HOOK_CONVENTIONS.record, { _meta: { [META]: meta }, ...(!full && own(payload, 'tool_input') ? { truncated: true } : {}) });
  if (own(payload, 'permission_mode') && payload.permission_mode !== state.approval) {
    state.approval = payload.permission_mode;
    emit('session_info', { agentSettings: { approval: payload.permission_mode } });
  }
  if (event === 'SessionEnd') emit('session_info', { endedAt: ts });
  if (['BeforeAgent', 'UserPromptSubmit'].includes(event) && typeof payload.prompt === 'string') {
    emit('message', { role: 'user', origin: 'prompt', ...(full ? { content: parts(payload.prompt) } : { content: [], truncated: true }) });
  }
  if (event === 'AfterAgent' && typeof payload.prompt_response === 'string') {
    emit('message', { role: 'assistant', author: 'model', ...(full ? { content: parts(payload.prompt_response) } : { content: [], truncated: true }) });
  }
  if (event === 'MessageDisplay' && payload.is_final === true && nativeId(payload.message_id) && typeof payload.displayed_text === 'string') {
    if (!state.messages.includes(payload.message_id)) {
      state.messages.push(payload.message_id);
      emit('message', { role: 'assistant', author: 'model', ...(full ? { content: parts(payload.displayed_text) } : { content: [], truncated: true }),
        _meta: { [META]: { message_id: payload.message_id } } });
    }
  }
  if (event === 'PostCompact' && typeof payload.compact_summary === 'string') {
    emit('message', { role: 'user', author: 'harness', origin: 'compaction', ...(full ? { content: parts(payload.compact_summary) } : { content: [], truncated: true }) });
    // Compaction affects model context. It does not prove recorder history loss.
  }
  if (agent === 'gemini-cli') {
    if (event === 'AfterTool') {
      const callId = deriveId(state.scope, 'observed-tool', state.observation);
      emit('tool_call', { callId, ...(nativeId(payload.tool_name) ? { name: payload.tool_name } : {}),
        ...(full && own(payload, 'tool_input') ? { input: payload.tool_input } : {}),
        ...(!full && own(payload, 'tool_input') ? { truncated: true } : {}) });
      const response = payload.tool_response ?? {};
      const fields = { callId, status: !object(payload.tool_response) ? 'unknown' : own(response, 'error') && response.error != null ? 'failed' : 'completed' };
      if (full && own(response, 'llmContent')) fields.content = parts(response.llmContent);
      if (!full && own(response, 'llmContent')) fields.truncated = true;
      if (object(response.error)) {
        fields.error = {};
        if (typeof response.error.message === 'string' && full) fields.error.message = response.error.message;
        if (own(response.error, 'type')) fields.error.code = response.error.type;
      }
      // Subsequent AfterTool hooks can still replace the output seen here.
      emit('tool_result', fields);
    }
    return records;
  }

  const callKey = (item) => {
    const useId = nativeId(item.tool_use_id);
    const providerId = nativeId(item.tool_call_id);
    const aliases = state.aliases;
    const lookup = (id) => id && own(aliases, id) ? aliases[id] : undefined;
    const known = [...new Set([lookup(useId), lookup(providerId)].filter(Boolean))];
    if (known.length > 1) {
      emit('session_info', { missing: ['tool_correlation'] });
      return undefined;
    }
    const id = known[0] ?? providerId ?? useId;
    if (id) for (const alias of [useId, providerId].filter(Boolean)) {
      Object.defineProperty(aliases, alias, { value: id, enumerable: true, writable: true, configurable: true });
    }
    return id;
  };
  const ensureCall = (item) => {
    const id = callKey(item);
    if (!id) return undefined;
    if (!own(state.calls, id)) {
      Object.defineProperty(state.calls, id, { value: { done: false }, writable: true, enumerable: true, configurable: true });
      emit('tool_call', { callId: id, ...(nativeId(item.tool_name) ? { name: item.tool_name } : {}),
        ...(full && own(item, 'tool_input') ? { _meta: { [META]: { observedRequestInput: item.tool_input } } } : {}),
        ...(!full && own(item, 'tool_input') ? { truncated: true } : {}) });
    }
    return id;
  };
  if (event === 'PreToolUse') ensureCall(payload);
  if (event === 'PermissionDenied') {
    const id = ensureCall(payload);
    emit('approval', { ...(id ? { callId: id } : {}), ...(typeof payload.subject === 'string' ? { subject: payload.subject } : {}), decision: 'denied',
      ...(payload.reason === 'classifier_blocked' ? { by: 'classifier' } : {}), native: { reason: payload.reason ?? null } });
    if (id) state.calls[id].denied = true;
  }
  if (event === 'PostToolUse' || event === 'PostToolUseFailure') {
    const id = ensureCall(payload);
    if (id && !state.calls[id].done) {
      const pending = { firstObservedAt: ts, status: event === 'PostToolUse' ? 'completed' : payload.is_interrupt === true ? 'interrupted' : 'failed' };
      if (full && own(payload, 'tool_input')) pending.input = payload.tool_input;
      if (full && own(payload, 'tool_response')) pending.observedResponse = payload.tool_response;
      if (full && typeof payload.error === 'string') pending.error = { message: payload.error };
      if (typeof payload.duration_ms === 'number' && Number.isFinite(payload.duration_ms) && payload.duration_ms >= 0 && payload.duration_ms <= Number.MAX_SAFE_INTEGER) pending.durationMs = payload.duration_ms;
      else if (typeof payload.duration_ms === 'string' && /^\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$/.test(payload.duration_ms)) {
        pending.nativeDurationMs = payload.duration_ms;
        emit('session_info', { missing: ['duration'] });
      }
      if (flags.changed || !full) pending.truncated = true;
      state.calls[id].pending = pending;
    }
  }
  const finish = (id, batch) => {
    const call = state.calls[id];
    if (call.done) return;
    const pending = call.pending ?? {};
    const row = { callId: id, status: batch ? ({ success: 'completed', error: call.denied ? 'denied' : 'failed', cancelled: 'cancelled' }[batch.status] ?? 'unknown') : pending.status ?? 'unknown' };
    if (own(pending, 'input')) row.input = pending.input;
    if (own(pending, 'durationMs')) row.durationMs = pending.durationMs;
    if (pending.error) row.error = pending.error;
    if (pending.truncated || !full) row.truncated = true;
    const response = batch?.tool_response;
    if (full && object(response) && own(response, 'response_parts')) row.content = parts(response.response_parts);
    if (!batch) emit('session_info', { missing: ['batch_tool_output'] });
    row._meta = { [META]: { ...(pending.firstObservedAt ? { firstObservedAt: pending.firstObservedAt } : {}),
      ...(pending.nativeDurationMs ? { duration_ms: pending.nativeDurationMs } : {}),
      ...(full && own(pending, 'observedResponse') ? { observedResponse: pending.observedResponse } : {}),
      ...(full && batch && own(batch, 'tool_input') ? { batchRequestInput: batch.tool_input } : {}),
      ...(!batch ? { incompleteBatch: true } : {}) } };
    emit('tool_result', row);
    state.calls[id] = { done: true };
  };
  if (event === 'PostToolBatch' && Array.isArray(payload.tool_calls)) {
    for (const item of payload.tool_calls) {
      if (!object(item)) continue;
      const id = ensureCall(item);
      if (id) finish(id, item);
    }
  }
  if (['Stop', 'StopFailure', 'SessionEnd'].includes(event)) {
    for (const [id, call] of Object.entries(state.calls)) if (!call.done && call.pending) finish(id);
  }
  return records;
}

export function record(agent, raw, { directory = process.env.ASR_OUTPUT_DIR, full = process.env.ASR_CONTENT === 'full', knownSecrets = environmentSecrets(process.env), now = () => new Date().toISOString() } = {}) {
  if (!['gemini-cli', 'qwen-code'].includes(agent) || !directory || !isAbsolute(directory) || !object(raw)
    || !nativeId(raw.session_id) || !nativeId(raw.hook_event_name)) return false;
  let payload, ts;
  const flags = { changed: false };
  try {
    ts = now();
    if (redactSecrets(raw.session_id, knownSecrets) !== raw.session_id) { markAgentLoss(directory, agent); return false; }
    payload = Buffer.byteLength(JSON.stringify(raw)) > 1024 * 1024
      ? { session_id: raw.session_id, hook_event_name: raw.hook_event_name, oversized: true }
      : sanitize(raw, knownSecrets, flags);
    if (payload.session_id !== raw.session_id) { markAgentLoss(directory, agent); return false; }
  } catch { markAgentLoss(directory, agent); return false; }
  const key = createHash('sha256').update(JSON.stringify([agent, raw.session_id])).digest('hex');
  const stream = join(directory, `${agent}-${key}.jsonl`);
  const start = payload.hook_event_name === 'SessionStart' && ['startup', 'clear'].includes(payload.source);
  const header = {
    agent: { name: agent }, sessionId: raw.session_id,
    producer: { name: `asr-hooks-${agent}`, version: '0.1.0', method: 'recorder', source: `${agent}-hooks` },
    ts, extensions: [HOOK_CONVENTIONS.extension], missing: [
      'reasoning', 'usage', 'timestamps', 'tools', 'file_changes', 'commits', 'subagents', 'copies', 'model',
      'approvals', 'agent_settings', 'exit_codes', 'hook_outcomes', 'hook_delivery', 'final_hook_rewrites',
      'instructions', 'messages', 'binary_content', 'tool_output', 'session_lifecycle',
      ...(agent === 'gemini-cli' ? ['tool_correlation', 'blocked_tool_results'] : []),
      ...(!full ? ['tool_input', 'content'] : []),
      ...(!start ? ['history_before_capture'] : []),
      ...(flags.changed ? ['redacted_content'] : []),
    ],
    ...(start ? { startedAt: ts, ...(typeof payload.cwd === 'string' && isAbsolute(payload.cwd) && full ? { cwd: payload.cwd } : {}) } : {}),
    ...(flags.changed ? { truncated: true } : {}),
  };
  return captureSession({ directory, agent, sessionId: raw.session_id, path: stream, statePath: `${stream}.state`,
    ts, header, maxState: MAX_STATE,
    initial: { scope: JSON.stringify([agent, raw.session_id]), position: 1, observation: 0, size: 0, calls: {}, aliases: {}, messages: [] },
    project(state, fresh) {
      const queued = state.preamble ?? [];
      const current = [];
      if (payload.oversized) current.push({ type: 'gap', reason: 'not_recorded', ts, detail: 'One recorder event exceeded the input size limit.' },
        { type: 'session_info', ts, missing: ['dropped_callbacks'] });
      else current.push(...project(agent, payload, state, ts, full, flags));
      state.observation++;
      const receipt = { records: current, full, changed: flags.changed };
      if (fresh && payload.hook_event_name === 'InstructionsLoaded'
        && queued.length < MAX_PREAMBLE_EVENTS
        && Buffer.byteLength(JSON.stringify([...queued, receipt])) <= MAX_PREAMBLE_BYTES) {
        state.preamble = [...queued, receipt];
        return undefined;
      }
      delete state.preamble;
      const records = [];
      if (fresh && !start) records.push({ type: 'gap', reason: 'not_recorded', ts: queued[0]?.records[0]?.ts ?? ts, detail: 'Capture began without an observed session start.' });
      if (fresh && queued.some(item => item.changed)) {
        header.missing.push('redacted_content');
        header.truncated = true;
      }
      if (fresh && queued.some(item => !item.full)) {
        header.missing.push('tool_input', 'content');
      }
      if (!fresh && flags.changed) records.push({ type: 'session_info', missing: ['redacted_content'], ts });
      records.push(...queued.flatMap(item => item.records), ...current);
      return records;
    },
  });
}
