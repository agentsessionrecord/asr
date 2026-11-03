import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, test } from 'node:test';
import { validateFile } from '../../../tools/validator/src/index.js';
import { META, parsePayload, record } from '../recorder.mjs';

let directory;
let tick;
const now = () => new Date(Date.UTC(2026, 0, 1, 0, 0, tick++)).toISOString();
beforeEach(() => { directory = mkdtempSync(join(tmpdir(), 'asr-hooks-test-')); tick = 0; });
afterEach(() => {
  try {
    for (const file of readdirSync(directory).filter((file) => file.endsWith('.jsonl'))) {
      const result = validateFile(join(directory, file));
      assert.equal(result.valid, true, JSON.stringify(result.diagnostics));
      assert.equal(result.diagnostics.filter((item) => item.severity === 'error').length, 0);
    }
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
const send = (agent, event, extra = {}, options = {}) => record(agent, { session_id: 'synthetic', hook_event_name: event, ...extra }, { directory, full: true, now, ...options });
const stream = () => join(directory, readdirSync(directory).find((name) => name.endsWith('.jsonl')));
const rows = () => readFileSync(stream(), 'utf8').trimEnd().split('\n').map(JSON.parse);
const fixture = (agent) => readFileSync(new URL(`./fixtures/${agent}.jsonl`, import.meta.url), 'utf8').trimEnd().split('\n').map(parsePayload);

test('Qwen holds instruction preambles until a fresh session start', () => {
  const agent = 'qwen-code';
  assert.equal(send(agent, 'InstructionsLoaded', { source_type: 'file', source_id: 'synthetic-instructions' }), true);
  assert.equal(readdirSync(directory).some(name => name.endsWith('.jsonl')), false);
  const checkpoint = readdirSync(directory).find(name => name.endsWith('.state'));
  assert.equal(statSync(join(directory, checkpoint)).mode & 0o777, 0o600);
  assert.equal(send(agent, 'SessionStart', { source: 'startup', cwd: '/work/app' }), true);
  const all = rows();
  assert.equal(all[0].startedAt, '2026-01-01T00:00:01.000Z');
  assert.equal(all[0].cwd, '/work/app');
  assert.equal(all.some(row => row.type === 'gap'), false);
  assert.equal(all.some(row => row.missing?.some(loss => ['history_before_capture', 'session_start_updates'].includes(loss))), false);
  const hooks = all.filter(row => row.type === `${META}/hook`);
  assert.deepEqual(hooks.map(row => row._meta[META].event), ['InstructionsLoaded', 'SessionStart']);
  assert.deepEqual(hooks.map(row => row.ts), ['2026-01-01T00:00:00.000Z', '2026-01-01T00:00:01.000Z']);
});

for (const [event, extra] of [['SessionStart', { source: 'resume' }], ['PreToolUse', { tool_use_id: 'later', tool_name: 'shell' }]]) {
  test(`a preamble followed by ${event} without a fresh start keeps missing history`, () => {
    send('qwen-code', 'InstructionsLoaded');
    send('qwen-code', event, extra);
    const all = rows();
    assert.equal(all[0].startedAt, undefined);
    assert.ok(all[0].missing.includes('history_before_capture'));
    assert.equal(all[1].type, 'gap');
  });
}

test('preamble holding is bounded and a start after the header keeps its receipt without rewriting', () => {
  for (let i = 0; i < 9; i++) send('qwen-code', 'InstructionsLoaded');
  assert.equal(rows().filter(row => row._meta?.[META]?.event === 'InstructionsLoaded').length, 9);
  const prefix = readFileSync(stream());
  send('qwen-code', 'SessionStart', { source: 'startup' });
  assert.deepEqual(readFileSync(stream()).subarray(0, prefix.length), prefix);
  assert.equal(rows()[0].startedAt, undefined);
  assert.equal(rows().at(-1)._meta[META].event, 'SessionStart');
  assert.equal(rows().at(-1).ts, '2026-01-01T00:00:09.000Z');
  assert.equal(rows().some(row => row.missing?.includes('session_start_updates')), false);
});

test('held preambles keep metadata capture private and redact before checkpointing', () => {
  send('qwen-code', 'InstructionsLoaded', { message: 'synthetic-private-text', source_id: 'synthetic-env-value' }, { full: false, knownSecrets: ['synthetic-env-value'] });
  for (const name of readdirSync(directory)) {
    const data = readFileSync(join(directory, name), 'utf8');
    assert.equal(data.includes('synthetic-private-text'), false);
    assert.equal(data.includes('synthetic-env-value'), false);
  }
  send('qwen-code', 'SessionStart', { source: 'startup' });
  assert.ok(rows()[0].missing.includes('redacted_content'));
  assert.ok(rows()[0].missing.includes('content'));
  assert.equal(rows().some(row => row.type === 'gap'), false);
});

test('a large instruction preamble flushes at the byte bound', () => {
  send('qwen-code', 'InstructionsLoaded', { message: 'x'.repeat(65536) });
  assert.equal(rows()[1].type, 'gap');
  assert.equal(rows().at(-1)._meta[META].event, 'InstructionsLoaded');
});

test('loss markers survive held preambles until the header is written', () => {
  send('qwen-code', 'InstructionsLoaded');
  const state = readdirSync(directory).find(name => name.endsWith('.state'));
  const lock = join(directory, state.replace(/\.state$/, '.lock'));
  mkdirSync(lock);
  assert.equal(send('qwen-code', 'InstructionsLoaded'), false);
  rmSync(lock, { recursive: true });
  send('qwen-code', 'InstructionsLoaded');
  assert.equal(readdirSync(directory).some(name => name.endsWith('.jsonl')), false);
  send('qwen-code', 'SessionStart', { source: 'startup' });
  const all = rows();
  assert.equal(all.filter(row => row.type === 'gap').length, 1);
  assert.ok(all.some(row => row.missing?.includes('dropped_callbacks')));
  assert.equal(all[0].missing.includes('history_before_capture'), false);
});

test('Qwen folds at batch receipt and preserves late effective arguments', () => {
  for (const payload of fixture('qwen-code')) assert.equal(record('qwen-code', payload, { directory, full: true, now }), true);
  const all = rows();
  const calls = all.filter((row) => row.type === 'tool_call');
  const results = all.filter((row) => row.type === 'tool_result');
  assert.equal(calls.length, 2);
  assert.equal('input' in calls[0], false);
  assert.deepEqual(calls[0]._meta[META].observedRequestInput, { command: 'printf requested' });
  assert.equal(results[0].input.command, 'printf effective');
  assert.equal(results[0].durationMs, 0);
  assert.equal(results[0].content[0].text, 'effective\n');
  assert.equal(results[0].ts, '2026-01-01T00:00:07.000Z');
  assert.equal(results[0]._meta[META].firstObservedAt, '2026-01-01T00:00:05.000Z');
  assert.ok(all.findIndex((row) => row._meta?.[META]?.event === 'Notification') < all.indexOf(results[0]));
  assert.deepEqual(all.filter((row) => row.type === 'approval').map((row) => [row.decision, row.by]), [['denied', 'classifier']]);
  assert.equal(results[1].status, 'denied');
  assert.equal(all.filter((row) => row.type === 'message' && row.role === 'assistant').length, 1);
  assert.equal(all[0].startedAt, '2026-01-01T00:00:01.000Z');
  assert.equal(all.at(-1).endedAt, '2026-01-01T00:00:14.000Z');
});

test('Gemini does not guess a relationship between ID-free BeforeTool and AfterTool', () => {
  for (const payload of fixture('gemini-cli')) assert.equal(record('gemini-cli', payload, { directory, full: true, now }), true);
  const all = rows();
  assert.equal(all.filter((row) => row.type === 'tool_call').length, 1);
  const call = all.find((row) => row.type === 'tool_call');
  const result = all.find((row) => row.type === 'tool_result');
  assert.equal(call.ts, result.ts);
  assert.equal(call.input.file_path, 'effective.txt');
  assert.equal(call.callId, result.callId);
  assert.equal(result.content[0].text, '  sample\r\n');
  assert.ok(all[0].missing.includes('tool_correlation'));
  assert.equal(all.some((row) => row.type === 'approval'), false);
  assert.equal(all.find((row) => row.role === 'user').author, undefined);
});

test('append leaves all complete bytes intact and restart keeps native identity', () => {
  send('qwen-code', 'SessionStart', { source: 'startup' });
  const prefix = readFileSync(stream());
  send('qwen-code', 'SessionStart', { source: 'resume' });
  send('qwen-code', 'Stop');
  const all = rows();
  assert.deepEqual(readFileSync(stream()).subarray(0, prefix.length), prefix);
  assert.equal(all.filter((row) => row.type === 'session').length, 1);
  assert.equal(all.some((row) => 'endedAt' in row), false);
  assert.equal(statSync(stream()).mode & 0o777, 0o600);
});

test('request hooks do not invent approvals and unavailable classifier does not invent a decider', () => {
  send('qwen-code', 'PermissionRequest', { tool_name: 'shell', tool_input: {} });
  assert.equal(rows().some((row) => row.type === 'approval'), false);
  send('qwen-code', 'PermissionDenied', { tool_use_id: 'call-1', tool_name: 'shell', reason: 'classifier_unavailable' });
  const decision = rows().find((row) => row.type === 'approval');
  assert.equal(decision.by, undefined);
  assert.equal(decision.scope, undefined);
  assert.equal(decision.person, undefined);
});

test('failure and interrupted outcomes flush once at a terminal callback without fabricating final content', () => {
  send('qwen-code', 'PostToolUseFailure', { tool_use_id: 'failed', tool_name: 'shell', tool_input: null, error: '', is_interrupt: true, duration_ms: 0 });
  send('qwen-code', 'Stop');
  send('qwen-code', 'PostToolBatch', { tool_calls: [{ tool_use_id: 'failed', tool_name: 'shell', status: 'error', tool_response: { response_parts: [{ text: 'late' }] } }] });
  const results = rows().filter((row) => row.type === 'tool_result');
  assert.equal(results.length, 1);
  assert.equal(results[0].input, null);
  assert.equal(results[0].status, 'interrupted');
  assert.deepEqual(results[0].error, { message: '' });
  assert.equal(results[0].content, undefined);
  assert.ok(rows().some((row) => row.missing?.includes('batch_tool_output')));
});

test('batch-only arguments stay in metadata because request arguments can be stale', () => {
  send('qwen-code', 'PostToolBatch', { tool_calls: [{ tool_use_id: 'late', tool_name: 'read_file', tool_input: { path: 'requested' }, status: 'cancelled', tool_response: { response_parts: [] } }] });
  const result = rows().find((row) => row.type === 'tool_result');
  assert.equal(result.input, undefined);
  assert.deepEqual(result.content, []);
  assert.equal(result.status, 'cancelled');
});

test('mode updates are verbatim, including null clears, with no asks inference', () => {
  send('qwen-code', 'SessionStart', { permission_mode: 'yolo' });
  send('qwen-code', 'Notification', { permission_mode: 'yolo' });
  send('qwen-code', 'Notification', { permission_mode: null });
  assert.deepEqual(rows().filter((row) => row.agentSettings).map((row) => row.agentSettings), [{ approval: 'yolo' }, { approval: null }]);
});

test('metadata capture omits text and marks its losses and shortened records', () => {
  send('qwen-code', 'UserPromptSubmit', { prompt: 'synthetic-private-text' }, { full: false });
  send('qwen-code', 'PreToolUse', { tool_use_id: 'metadata', tool_name: 'shell', tool_input: { command: 'synthetic-private-text' } }, { full: false });
  send('qwen-code', 'PostToolBatch', { tool_calls: [{ tool_use_id: 'metadata', status: 'success', tool_response: { response_parts: [{ text: 'synthetic-private-text' }] } }] }, { full: false });
  assert.equal(readFileSync(stream(), 'utf8').includes('synthetic-private-text'), false);
  assert.ok(rows()[0].missing.includes('tool_input'));
  assert.equal(rows().find((row) => row.type === 'message').truncated, true);
});

test('known credentials, secret keys, opaque signatures and media bytes never reach stream or state', () => {
  send('qwen-code', 'PostToolUse', { tool_use_id: 'redacted', tool_name: 'shell', tool_input: { password: 'synthetic-secret', key: 'synthetic-env-value' }, tool_response: { signature: 'synthetic-signature', llmContent: 'Bearer synthetic-auth' } }, { knownSecrets: ['synthetic-env-value'] });
  send('qwen-code', 'PostToolBatch', { tool_calls: [{ tool_use_id: 'redacted', status: 'success', tool_response: { response_parts: [{ inlineData: { data: 'synthetic-bytes', mimeType: 'image/png' } }, { text: 'opaque', thoughtSignature: 'synthetic-signature' }] } }] });
  for (const name of readdirSync(directory)) {
    if (!statSync(join(directory, name)).isFile()) continue;
    const data = readFileSync(join(directory, name), 'utf8');
    for (const value of ['synthetic-secret', 'synthetic-env-value', 'synthetic-signature', 'synthetic-bytes', 'synthetic-auth']) assert.equal(data.includes(value), false);
  }
  assert.ok(rows()[0].missing.includes('redacted_content'));
});

test('credential-shaped text is excluded even outside structured secret fields', () => {
  const cloudKey = 'AKIA' + 'A'.repeat(16);
  const jwt = 'eyJ' + 'a'.repeat(12) + '.' + 'b'.repeat(12) + '.' + 'c'.repeat(12);
  const text = `${cloudKey} ${jwt} api_key=synthetic-value https://synthetic:synthetic@example.invalid/`;
  send('gemini-cli', 'AfterAgent', { prompt_response: text });
  const data = readFileSync(stream(), 'utf8');
  for (const secret of [cloudKey, jwt, 'synthetic-value', 'synthetic:synthetic@']) assert.equal(data.includes(secret), false);
  assert.equal(rows().find((row) => row.type === 'message').truncated, true);
});

test('large native integers are preserved exactly without altering core counts', () => {
  const payload = parsePayload('{"session_id":"synthetic","hook_event_name":"PostToolUse","tool_name":"shell","tool_use_id":"large","tool_input":{"id":9007199254740993},"duration_ms":9007199254740993}');
  record('qwen-code', payload, { directory, full: true, now });
  send('qwen-code', 'Stop');
  const result = rows().find((row) => row.type === 'tool_result');
  assert.equal(result.input.id, '9007199254740993');
  assert.equal(result.durationMs, undefined);
  assert.equal(result._meta[META].duration_ms, '9007199254740993');
  assert.ok(rows().some((row) => row.missing?.includes('duration')));
});

test('unknown Google content uses a vendor wrapper beside known text', () => {
  send('gemini-cli', 'AfterTool', { tool_name: 'read_file', tool_response: { llmContent: [{ document: { name: 'notes.pdf' } }, { text: 'known' }] } });
  const content = rows().find(row => row.type === 'tool_result').content;
  assert.deepEqual(content, [{ type: `${META}/content`, _meta: { [META]: { native: { document: { name: 'notes.pdf' } } } } }, { type: 'text', text: 'known' }]);
});

test('Qwen provider IDs join differing per-tool and batch tool_use_id values', () => {
  send('qwen-code', 'PreToolUse', { tool_use_id: 'internal-1', tool_call_id: 'provider-1', tool_name: 'shell', tool_input: { command: 'requested' } });
  send('qwen-code', 'PostToolUse', { tool_use_id: 'internal-1', tool_call_id: 'provider-1', tool_name: 'shell', tool_input: { command: 'effective' } });
  send('qwen-code', 'PostToolBatch', { tool_calls: [{ tool_use_id: 'provider-1', tool_name: 'shell', status: 'success', tool_response: { response_parts: [{ text: 'effective\n' }] } }] });
  const all = rows();
  assert.equal(all.filter((row) => row.type === 'tool_call').length, 1);
  assert.equal(all.filter((row) => row.type === 'tool_result').length, 1);
  const result = all.find((row) => row.type === 'tool_result');
  assert.equal(result.callId, 'provider-1');
  assert.equal(result.input.command, 'effective');
});

test('native IDs with reserved property names do not modify recorder state prototypes', () => {
  send('qwen-code', 'PreToolUse', { tool_use_id: '__proto__', tool_name: 'shell' });
  send('qwen-code', 'PostToolBatch', { tool_calls: [{ tool_use_id: '__proto__', tool_name: 'shell', status: 'success' }] });
  assert.equal(rows().filter((row) => row.type === 'tool_call').length, 1);
  assert.equal(rows().filter((row) => row.type === 'tool_result').length, 1);
});

test('lock contention fails open and a later receipt records the known gap', () => {
  send('qwen-code', 'SessionStart', { source: 'startup' });
  const lock = `${stream()}.lock`;
  mkdirSync(lock);
  assert.equal(send('qwen-code', 'Notification'), false);
  rmSync(lock, { recursive: true });
  send('qwen-code', 'Stop');
  assert.equal(rows().filter((row) => row.type === 'gap').length, 1);
});

test('unsafe directories and stream symlinks are refused without modifying their targets', () => {
  chmodSync(directory, 0o755);
  assert.equal(send('qwen-code', 'SessionStart'), false);
  chmodSync(directory, 0o700);
  const target = join(directory, 'target');
  writeFileSync(target, 'unchanged', { mode: 0o600 });
  const key = createHash('sha256').update(JSON.stringify(['qwen-code', 'synthetic'])).digest('hex');
  const link = join(directory, `qwen-code-${key}.jsonl`);
  symlinkSync(target, link);
  assert.equal(send('qwen-code', 'SessionStart'), false);
  assert.equal(readFileSync(target, 'utf8'), 'unchanged');
  rmSync(link);
});

test('missing checkpoint seals intact history with a gap and never rewrites its prefix', () => {
  send('qwen-code', 'SessionStart', { source: 'startup' });
  const prefix = readFileSync(stream());
  rmSync(`${stream()}.state`);
  assert.equal(send('qwen-code', 'Stop'), false);
  assert.deepEqual(readFileSync(stream()).subarray(0, prefix.length), prefix);
  assert.equal(rows().at(-2).type, 'gap');
  assert.ok(rows().at(-1).missing.includes('capture_stopped'));
  const sealed = readFileSync(stream());
  assert.equal(send('qwen-code', 'Stop'), false);
  assert.deepEqual(readFileSync(stream()), sealed);
});

test('built command is silent and exits zero on malformed input and I/O failures', () => {
  const cli = fileURLToPath(new URL('../../qwen-code/dist/record.mjs', import.meta.url));
  for (const input of ['{', '[]', JSON.stringify({ session_id: 'synthetic', hook_event_name: 'SessionStart' })]) {
    assert.equal(execFileSync(process.execPath, [cli, 'qwen-code'], { input, env: { PATH: process.env.PATH, ASR_OUTPUT_DIR: '/dev/null/refused' }, encoding: 'utf8' }), '');
  }
  assert.equal(readdirSync(directory).length, 0);
});

test('independent concurrent command hooks preserve complete lines and report contention', async () => {
  const cli = fileURLToPath(new URL('../../qwen-code/dist/record.mjs', import.meta.url));
  send('qwen-code', 'SessionStart');
  await Promise.all(Array.from({ length: 6 }, () => new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [cli, 'qwen-code'], { env: { PATH: process.env.PATH, ASR_OUTPUT_DIR: directory }, stdio: ['pipe', 'pipe', 'pipe'] });
    child.on('error', reject);
    child.on('close', (code) => code === 0 ? resolve() : reject(new Error(`exit ${code}`)));
    child.stdin.end(JSON.stringify({ session_id: 'synthetic', hook_event_name: 'Notification' }));
  })));
  send('qwen-code', 'Stop');
  assert.ok(rows().length >= 4);
  assert.equal(new Set(rows().map((row) => row.id)).size, rows().length);
});

test('published synthetic samples match their hook fixtures and pass the validator CLI', () => {
  for (const agent of ['gemini-cli', 'qwen-code']) {
    const subdir = join(directory, agent);
    mkdirSync(subdir, { mode: 0o700 });
    tick = 0;
    for (const payload of fixture(agent)) record(agent, payload, { directory: subdir, full: true, now });
    const file = readdirSync(subdir).find((name) => name.endsWith('.jsonl'));
    const actual = readFileSync(join(subdir, file));
    assert.equal(actual.toString(), readFileSync(new URL(`../../${agent}/samples/synthetic.jsonl`, import.meta.url), 'utf8'));
    const validator = fileURLToPath(new URL('../../../tools/validator/bin/asr-validate.js', import.meta.url));
    const result = JSON.parse(execFileSync(process.execPath, [validator, '--json', join(subdir, file)], { encoding: 'utf8' }));
    assert.equal(result.errors, 0);
  }
});


test('live start captures repository facts once and Gemini thought text is a summary', () => {
  const repo = join(directory, 'repo'); mkdirSync(repo);
  execFileSync('git', ['-C', repo, 'init', '-q', '-b', 'initial']);
  assert.equal(send('gemini-cli', 'SessionStart', { source: 'startup', cwd: repo }), true);
  assert.equal(rows()[0].repos[0].path, repo);
  assert.equal(rows()[0].repos[0].branch, 'initial');
  execFileSync('git', ['-C', repo, 'checkout', '-q', '-b', 'later']);
  assert.equal(send('gemini-cli', 'SessionStart', { source: 'resume', cwd: repo }), true);
  assert.equal(rows()[0].repos[0].branch, 'initial');
  send('gemini-cli', 'AfterTool', { tool_name: 'read', tool_response: { llmContent: [{ thought: true, text: 'summary' }, { thought: true, text: '' }, { thought: true, thoughtSignature: 'opaque' }] } });
  assert.deepEqual(rows().find(row => row.type === 'tool_result').content, [
    { type: 'reasoning', visibility: 'summary', summary: ['summary'] }, { type: 'reasoning', visibility: 'omitted' }, { type: 'reasoning', visibility: 'omitted' }]);
});
