import { createHash } from 'node:crypto';
import { join, resolve } from 'node:path';
import { environmentSecrets, credentialValues, isSecretKey, isOpaqueKey, redactSecrets } from '../../packages/writer/dist/index.js';
import { captureSession, HOOK_CONVENTIONS, markAgentLoss } from '../../packages/writer/dist/capture.js';

export const NS = HOOK_CONVENTIONS.metadata;
export const losses = ['reasoning', 'usage', 'timestamps', 'tool_output', 'exit_codes', 'file_changes',
  'commits', 'subagents', 'copies', 'model', 'approvals', 'agent_settings', 'tools', 'instructions',
  'message_authorship', 'message_person', 'session_user', 'hook_outcomes', 'hook_input_rewrites',
  'media', 'bounded_capture', 'assistant_messages', 'native_record_ids', 'parent_lineage',
  'triggers', 'session_lifecycle', 'unmapped_hook_fields', 'result_updates', 'history_before_capture'];
const MAX_EVENT = 1024 * 1024;
const MAX_CALLS = 4096;
const hash = value => createHash('sha256').update(value).digest('hex');
const owns = (object, key) => Object.hasOwn(object, key);

// JSON.parse's source context preserves native integers before rounding.
export function parse(text) {
  return JSON.parse(text, (_key, value, context) => typeof value === 'number' &&
    Number.isInteger(value) && !Number.isSafeInteger(value) ? context.source : value);
}

function scrub(value, env, full) {
  const secrets = [...environmentSecrets(env), ...credentialValues(value)];
  let changed = false;
  const walk = (item, key = '') => {
    if (isSecretKey(key) || isOpaqueKey(key)) {
      changed = true;
      return '[redacted]';
    }
    if (typeof item === 'string') {
      const result = redactSecrets(item, secrets);
      changed ||= result !== item;
      return result;
    }
    if (typeof item === 'bigint') return String(item);
    if (Array.isArray(item)) return item.map(x => walk(x));
    if (item && typeof item === 'object') return Object.fromEntries(Object.entries(item).flatMap(([k, v]) => {
      if (redactSecrets(k, secrets) !== k) { changed = true; return []; }
      return [[k, walk(v, k)]];
    }));
    if (typeof item === 'number' && (!Number.isFinite(item) || Math.abs(item) > Number.MAX_SAFE_INTEGER)) {
      throw new Error('Unsafe native number from an in-process hook');
    }
    return item;
  };
  // The caller projects only known fields. Payloads and provider headers are never dumped.
  const cleaned = walk(value);
  return { value: cleaned, changed, full };
}

function parts(value) {
  if (typeof value === 'string') return [{ type: 'text', text: value }];
  if (Array.isArray(value)) return value.filter(part => part?.type === 'text' && typeof part.text === 'string')
    .map(({ text }) => ({ type: 'text', text }));
  return undefined;
}

/** Normalized observations carry receipt order, never policy authority. */
export function project(event, state, ts, full) {
  const records = [];
  const add = record => records.push({ ...record, ts });
  const meta = { event: event.event };
  for (const field of ['facts', 'requestedInput']) if (full && owns(event, field)) meta[field] = event[field];
  add({ type: HOOK_CONVENTIONS.record, event: event.event, _meta: { [NS]: meta }, ...(!full ? { truncated: true } : {}) });
  if (event.start && !state.started) {
    // Resuming an existing native session is not the original start.
    state.started = true;
  }
  if (event.end) add({ type: 'session_info', endedAt: ts });
  if (typeof event.title === 'string') add({ type: 'session_info', title: event.title });
  if (event.settings) add({ type: 'session_info', agentSettings: event.settings });
  if (event.message) {
    const content = full ? parts(event.message.content) : [];
    if (content) add({ type: 'message', role: event.message.role, content,
      ...(event.message.author ? { author: event.message.author } : {}),
      ...(event.message.origin ? { origin: event.message.origin } : {}),
      ...(!full || (Array.isArray(event.message.content) && content.length !== event.message.content.length) ? { truncated: true } : {}) });
  }
  const callId = typeof event.callId === 'string' && event.callId ? event.callId : undefined;
  if (event.call && callId && !owns(state.calls, callId)) {
    add({ type: 'tool_call', callId, ...(event.name ? { name: event.name } : {}),
      ...(event.parentCallId ? { parentCallId: event.parentCallId } : {}),
      ...(full && owns(event, 'requestedInput') ? { _meta: { [NS]: { requestedInput: event.requestedInput } } } : {}),
      ...(!full ? { truncated: true } : {}) });
    state.calls[callId] = true;
  }
  if (event.approval) {
    const approval = { type: 'approval', decision: event.approval.decision,
      ...(callId ? { callId } : {}),
      ...(typeof event.approval.subject === 'string' ? { subject: event.approval.subject } : {}),
      ...(event.approval.by ? { by: event.approval.by } : {}),
      ...(event.approval.scope ? { scope: event.approval.scope } : {}),
      ...(full && event.facts ? { native: event.facts } : {}) };
    add(approval);
  }
  if (event.result && (!callId || !owns(state.results, callId))) {
    const result = { type: 'tool_result', status: event.result.status || 'unknown', ...(callId ? { callId } : {}) };
    if (full) {
      if (owns(event.result, 'content')) {
        const content = parts(event.result.content);
        if (content) {
          result.content = content;
          if (Array.isArray(event.result.content) && content.length !== event.result.content.length) result.truncated = true;
        }
        else result._meta = { [NS]: { output: event.result.content } };
      }
      if (owns(event.result, 'input')) result.input = event.result.input;
      if (event.result.error !== undefined) {
        const error = event.result.error;
        result.error = error && typeof error === 'object' && !Array.isArray(error)
          ? { ...(typeof error.message === 'string' ? { message: error.message } : {}),
            ...(owns(error, 'code') ? { code: error.code } : {}) }
          : { message: String(error) };
      }
    } else result.truncated = true;
    if (Number.isFinite(event.result.durationMs) && event.result.durationMs >= 0) result.durationMs = event.result.durationMs;
    add(result);
    if (callId) state.results[callId] = true;
  }
  return records;
}

/** Shared command-hook storage adds bounded resume support to the writer library. */
export function record(agent, observation, options = {}) {
  const env = options.env || process.env;
  if (!env.ASR_OUTPUT_DIR || typeof observation?.sessionId !== 'string' || !observation.sessionId) return false;
  const ts = options.now || new Date().toISOString();
  const root = resolve(env.ASR_OUTPUT_DIR);
  const full = env.ASR_CONTENT === 'full';
  const base = join(root, `${agent}-${hash(observation.sessionId)}`);
  let clean;
  try {
    if (redactSecrets(observation.sessionId, environmentSecrets(env)) !== observation.sessionId) { markAgentLoss(root, agent); return false; }
    if (Buffer.byteLength(JSON.stringify(observation, (_key, value) => typeof value === 'bigint' ? String(value) : value)) > MAX_EVENT) {
      clean = { value: { sessionId: observation.sessionId, event: observation.event, oversized: true }, changed: false };
    } else clean = scrub(observation, env, full);
    // A secret-valued identity cannot safely become a different join key.
    if (['sessionId', 'callId', 'parentCallId', 'turnId'].some(key => clean.value[key] !== observation[key])) {
      if (!clean.value.oversized) { markAgentLoss(root, agent); return false; }
    }
  } catch { markAgentLoss(root, agent); return false; }
  const event = clean.value;
  const header = { agent: { name: agent }, sessionId: event.sessionId,
    producer: { name: `asr-hooks-${agent}`, version: '0.1.0', method: 'recorder', source: `${agent}-hooks` },
    missing: [...losses, ...(!full ? ['content', 'paths'] : []), ...(clean.changed ? ['redacted_content'] : [])],
    extensions: [HOOK_CONVENTIONS.extension], ts,
    ...(event.start && event.fresh ? { startedAt: ts, ...(full && typeof event.cwd === 'string' && event.cwd.startsWith('/') ? { cwd: event.cwd } : {}) } : {}) };
  return captureSession({ directory: root, agent, sessionId: event.sessionId, path: `${base}.jsonl`,
    statePath: `${base}.state`, lockPath: `${base}.lock`, ts, header, maxState: MAX_EVENT,
    initial: { position: 1, size: 0, calls: {}, results: {}, started: !!event.start },
    project(state, fresh) {
      state.calls = Object.assign(Object.create(null), state.calls);
      state.results = Object.assign(Object.create(null), state.results);
      let records = [];
      if (fresh && !(event.start && event.fresh)) records.push({ type: 'gap', reason: 'not_recorded',
        detail: 'Capture began after session start.', ts });
      if (clean.changed) records.push({ type: 'session_info', missing: ['redacted_content'], ts });
      if (event.oversized) records.push({ type: 'gap', reason: 'not_recorded', detail: 'One recorder event exceeded the input size limit.', ts },
        { type: 'session_info', missing: ['dropped_callbacks'], ts });
      else if (Object.keys(state.calls).length >= MAX_CALLS) {
        records.push({ type: 'gap', reason: 'not_recorded', detail: 'Capture stopped at the call capacity limit.', ts },
          { type: 'session_info', missing: ['capture_stopped'], ts });
        state.stopped = true;
      } else records.push(...project(event, state, ts, full));
      if (clean.changed || event.truncated) records = records.map(item => ({ ...item, truncated: true }));
      if (event.turnId) records = records.map(item => ({ ...item, turnId: String(event.turnId) }));
      return records;
    },
  });
}
