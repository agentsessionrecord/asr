import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync, statSync, chmodSync, appendFileSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { validate } from '../../../tools/validator/src/index.js';
import { adapt } from '../adapters.mjs';
import { record, parse, NS } from '../recorder.mjs';
import { configuration, events } from '../configure.mjs';
import piPlugin from '../../pi/index.mjs';
import ampPlugin from '../../amp/index.mjs';

const agents = ['goose', 'pi', 'cline', 'kimi-code', 'grok-build', 'deepseek-harness', 'crush', 'mux', 'amp'];
const native = agent => readFileSync(new URL(`../../${agent}/fixtures/native.jsonl`, import.meta.url), 'utf8').trimEnd().split('\n').map(parse);
const directory = t => { const path = mkdtempSync(join(tmpdir(), 'asr-hooks-test-')); t.after(() => rmSync(path, { recursive: true, force: true })); return path; };
const output = path => readdirSync(path).filter(name => name.endsWith('.jsonl')).map(name => readFileSync(join(path, name), 'utf8'));
const rows = path => output(path).flatMap(text => text.trimEnd().split('\n').map(parse));
const envFor = path => ({ ASR_OUTPUT_DIR: path, ASR_CONTENT: 'full' });
const send = (path, event, agent = 'goose') => record(agent, { sessionId: 'synthetic-session', event: 'fixture', ...event }, { env: envFor(path), now: '2026-11-01T00:00:00Z' });

for (const agent of agents) test(`${agent}: source-shaped fixture validates and pairs one result`, async t => {
  const path = directory(t);
  if (agent === 'pi' || agent === 'amp') {
    const old = { output: process.env.ASR_OUTPUT_DIR, content: process.env.ASR_CONTENT };
    process.env.ASR_OUTPUT_DIR = path; process.env.ASR_CONTENT = 'full';
    try {
      const handlers = new Map();
      await (agent === 'pi' ? piPlugin : ampPlugin)({ on: (name, handler) => handlers.set(name, handler) });
      const context = { cwd: '/work/synthetic', sessionManager: { getSessionId: () => 'synthetic-session' } };
      for (const event of native(agent)) {
        const result = await handlers.get(event.type || event.event)(event, context);
        assert.deepEqual(result, agent === 'amp' && event.event === 'tool.call' ? { action: 'allow' } : undefined);
      }
    } finally {
      for (const [key, value] of [['ASR_OUTPUT_DIR', old.output], ['ASR_CONTENT', old.content]]) {
        if (value === undefined) delete process.env[key]; else process.env[key] = value;
      }
    }
  } else for (const payload of native(agent)) assert.equal(record(agent, adapt(agent, payload), { env: envFor(path) }), true);
  assert.equal(output(path).length, 1);
  for (const text of output(path)) {
    const report = validate(text);
    assert.equal(report.valid, true, JSON.stringify(report.diagnostics));
    assert.deepEqual(report.diagnostics.filter(d => d.severity === 'error'), []);
  }
  const records = rows(path), call = records.find(r => r.type === 'tool_call'), result = records.find(r => r.type === 'tool_result');
  assert.equal(records[0].producer.method, 'recorder');
  assert.equal(records.filter(r => r.type === 'tool_result').length, 1);
  assert.equal(result.callId, call.callId);
  assert.equal(call.input, undefined);
  if (!['mux'].includes(agent)) assert.deepEqual(result.input, { command: 'printf effective' });
  assert.equal(records.some(r => r.type === 'session_info' && !!r.endedAt), ['goose', 'kimi-code', 'grok-build', 'crush'].includes(agent));
});

test('append preserves prefix, deduplicates results, and keeps intervening observations', t => {
  const path = directory(t);
  send(path, { call: true, callId: 'one', name: 'shell', requestedInput: { command: 'old' } });
  const prefix = output(path)[0];
  send(path, { message: { role: 'user', content: 'between\n' } });
  send(path, { callId: 'one', result: { status: 'completed', input: null, content: '', durationMs: 0 } });
  send(path, { callId: 'one', result: { status: 'failed' } });
  assert.ok(output(path)[0].startsWith(prefix));
  const records = rows(path);
  assert.equal(records.filter(r => r.type === 'session').length, 1);
  assert.equal(records.filter(r => r.type === 'tool_result').length, 1);
  assert.deepEqual(records.find(r => r.type === 'tool_result').input, null);
  assert.ok(records.findIndex(r => r.type === 'message') < records.findIndex(r => r.type === 'tool_result'));
});

test('requests, absent policies and successful tools do not invent approvals', t => {
  const path = directory(t);
  for (const payload of [
    { event: 'PreToolUseResult', decision: 'allow', policy_evaluated: false },
    { event: 'PreToolUseResult', decision: 'allow', policy_evaluated: true, cause: 'hook_failure' },
    { event: 'PermissionRequest' },
  ]) record('goose', adapt('goose', { session_id: 's', ...payload }), { env: envFor(path) });
  assert.equal(rows(path).filter(r => r.type === 'approval').length, 0);
});

test('explicit hook failure denial and permission cancellation keep only stated attribution', t => {
  const path = directory(t);
  record('goose', adapt('goose', { session_id: 's', event: 'PreToolUseResult', decision: 'deny', cause: 'hook_failure' }), { env: envFor(path) });
  record('crush', adapt('crush', { session_id: 's', event: 'PermissionResult', decision: 'cancelled' }), { env: envFor(path) });
  const approvals = rows(path).filter(r => r.type === 'approval');
  assert.equal(approvals.find(r => r.decision === 'denied').by, 'fallback');
  assert.equal(approvals.find(r => r.decision === 'cancelled').by, undefined);
  assert.ok(approvals.every(r => !r.person && !r.scope));
});

test('metadata mode omits input, output and prompt text', t => {
  const path = directory(t);
  record('goose', { sessionId: 's', event: 'private', call: true, callId: 'one', name: 'shell', requestedInput: 'SYNTHETIC CONTENT',
    message: { role: 'user', content: 'SYNTHETIC CONTENT' }, facts: { reason: 'SYNTHETIC CONTENT' }, result: { content: 'SYNTHETIC CONTENT' } },
  { env: { ASR_OUTPUT_DIR: path } });
  assert.ok(!output(path)[0].includes('SYNTHETIC CONTENT'));
  assert.ok(rows(path)[0].missing.includes('content'));
});

test('known secret values and sensitive keys are excluded with declared losses', t => {
  const path = directory(t), synthetic = 'synthetic-value-only-for-testing';
  record('goose', { sessionId: 's', event: 'private', message: { role: 'user', content: synthetic }, facts: { password: synthetic } },
    { env: { ...envFor(path), TEST_API_KEY: synthetic } });
  assert.ok(!output(path)[0].includes(synthetic));
  assert.ok(rows(path).some(r => r.missing?.includes('redacted_content')));
  assert.equal(rows(path).find(r => r.type === 'message').truncated, true);
});

test('secret-valued native identities disable a receipt instead of merging joins', t => {
  const path = directory(t), secret = 'synthetic-secret-identity';
  for (const key of ['sessionId', 'callId', 'parentCallId', 'turnId']) {
    assert.equal(record('goose', { sessionId: 's', event: 'fixture', call: true, callId: 'one', [key]: secret },
      { env: { ...envFor(path), TEST_API_KEY: secret } }), false);
  }
  assert.deepEqual(output(path), []);
});

test('large native integers survive JSON decoding exactly', () => {
  assert.equal(parse('{"id":9007199254740993123456789}').id, '9007199254740993123456789');
});

test('lock contention is fast and next receipt marks a gap', t => {
  const path = directory(t); send(path, {});
  const state = readdirSync(path).find(name => name.endsWith('.state'));
  writeFileSync(join(path, state.replace('.state', '.lock')), '', { mode: 0o600 });
  assert.equal(send(path, { end: true }), false);
  rmSync(join(path, state.replace('.state', '.lock')));
  assert.equal(send(path, {}), true);
  assert.equal(rows(path).filter(r => r.type === 'gap' && r.detail.includes('contention')).length, 1);
});

test('incomplete prior append fails open without modifying the stream', t => {
  const path = directory(t); send(path, {});
  const file = join(path, readdirSync(path).find(name => name.endsWith('.jsonl')));
  appendFileSync(file, '{'); const prefix = readFileSync(file, 'utf8');
  assert.equal(send(path, {}), false);
  assert.equal(readFileSync(file, 'utf8'), prefix);
});

test('unsafe output directories and oversized events fail open', t => {
  const path = directory(t); chmodSync(path, 0o777);
  assert.equal(send(path, {}), false);
  chmodSync(path, 0o700);
  assert.equal(send(path, { message: { role: 'user', content: 'x'.repeat(1024 * 1024) } }), true);
  assert.ok(rows(path).some(row => row.type === 'gap' && row.detail.includes('input size')));
  assert.equal(statSync(join(path, readdirSync(path).find(name => name.endsWith('.jsonl')))).mode & 0o777, 0o600);
});

test('command entrypoint is silent and successful on malformed JSON and unwritable output', t => {
  const path = directory(t);
  writeFileSync(join(path, 'not-a-directory'), 'synthetic');
  for (const input of ['{bad', JSON.stringify({ session_id: 's', event: 'Stop' })]) {
    const run = spawnSync(process.execPath, [resolve('plugins/remaining-core/command.mjs'), 'goose'],
      { input, encoding: 'utf8', env: { ...process.env, ASR_OUTPUT_DIR: join(path, 'not-a-directory', 'child') } });
    assert.equal(run.status, 0); assert.equal(run.stdout, ''); assert.equal(run.stderr, '');
  }
  assert.deepEqual(readdirSync(path), ['not-a-directory']);
});

test('command entrypoint fails open when its runtime dependencies are unavailable', t => {
  const path = directory(t), command = join(path, 'command.mjs');
  writeFileSync(command, readFileSync(resolve('plugins/remaining-core/command.mjs')));
  const run = spawnSync(process.execPath, [command, 'goose'], { input: '{}', encoding: 'utf8' });
  assert.equal(run.status, 0);
  assert.equal(run.stdout, '');
  assert.equal(run.stderr, '');
});

test('configuration uses only source-supported event names and one second timeouts', () => {
  for (const agent of Object.keys(events)) {
    const text = configuration(agent);
    assert.ok(text.includes('command.mjs'));
    if (agent !== 'kimi-code') assert.deepEqual(Object.keys(JSON.parse(text).hooks), events[agent]);
    else assert.ok(text.includes('[[hooks]]'));
  }
});

test('Mux MCP transport returns no-op JSON for hook observations', t => {
  const path = directory(t);
  const input = [{ jsonrpc: '2.0', id: 1, method: 'initialize', params: {} },
    ...native('mux').map((arguments_, n) => ({ jsonrpc: '2.0', id: n + 2, method: 'tools/call', params: { name: 'observe', arguments: arguments_ } }))]
    .map(r => JSON.stringify(r)).join('\n') + '\n';
  const run = spawnSync(process.execPath, [resolve('plugins/mux/server.mjs')], { input, encoding: 'utf8', env: { ...process.env, ...envFor(path) } });
  assert.equal(run.status, 0); assert.equal(run.stderr, '');
  const responses = run.stdout.trim().split('\n').map(parse);
  assert.equal(responses[0].result.serverInfo.name, 'asr-mux-recorder');
  assert.ok(responses.slice(1).every(r => r.result.content[0].text === '{}'));
  assert.equal(validate(output(path)[0]).valid, true);
});


test('fresh command hooks capture repository facts and never replace them on resume', t => {
  const path = directory(t), repo = join(path, 'repo'); mkdirSync(repo);
  assert.equal(spawnSync('git', ['-C', repo, 'init', '-q', '-b', 'initial']).status, 0);
  assert.equal(send(path, { start: true, fresh: true, cwd: repo }), true);
  const header = rows(path)[0];
  assert.deepEqual(header.repos, [{ path: repo, branch: 'initial' }]);
  assert.equal(spawnSync('git', ['-C', repo, 'checkout', '-q', '-b', 'later']).status, 0);
  assert.equal(send(path, { start: true, fresh: false, cwd: repo }), true);
  assert.deepEqual(rows(path)[0], header);
});
