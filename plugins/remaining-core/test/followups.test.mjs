import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { adapt } from '../adapters.mjs';
import { configuration, events, kimiV2Events } from '../configure.mjs';
import { buildPlugin } from '../build.mjs';
import { record, parse, NS } from '../recorder.mjs';
import { validate } from '../../../tools/validator/src/index.js';
import { secretCases } from '../../../packages/writer/test/secret-cases.mjs';

function setup(t) {
  const root = mkdtempSync(join(tmpdir(), 'asr-followups-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const output = join(root, 'output');
  const env = { ASR_OUTPUT_DIR: output, ASR_CONTENT: 'full' };
  const text = () => readFileSync(join(output, readdirSync(output).find(name => name.endsWith('.jsonl'))), 'utf8');
  return { root, env, text, rows: () => text().trimEnd().split('\n').map(parse) };
}

test('Kimi 2.x preserves ordered text, explicit decisions, errors and callback facts', t => {
  const { env, text, rows } = setup(t);
  const native = readFileSync(new URL('../../kimi-code/fixtures/native-v2.jsonl', import.meta.url), 'utf8').trimEnd().split('\n').map(parse);
  for (const payload of native) assert.equal(record('kimi-code', adapt('kimi-code', payload), { env }), true);
  assert.equal(validate(text()).valid, true);
  const records = rows(), messages = records.filter(r => r.type === 'message');
  assert.equal(messages.length, 1);
  assert.deepEqual(messages[0].content, [{ type: 'text', text: 'first\n' }, { type: 'text', text: 'last雪' }]);
  assert.equal(messages[0].truncated, true);
  assert.ok(!text().includes('https://example.invalid'));
  assert.deepEqual(records.filter(r => r.type === 'approval').map(r => [r.callId, r.decision, r.scope, r.by]), [
    ['call-1', 'approved', 'session', undefined], ['denied-call', 'denied', undefined, undefined], ['cancelled-call', 'cancelled', undefined, undefined],
  ]);
  const results = records.filter(r => r.type === 'tool_result');
  assert.deepEqual(results.map(r => r.status), ['completed', 'failed']);
  assert.deepEqual(results[0].input, { command: 'printf effective' });
  assert.deepEqual(results[1].error, { message: 'synthetic failure', code: 'E_SYNTHETIC' });
  const hook = name => records.find(r => r.type === `${NS}/hook` && r.event === name);
  assert.equal(hook('SessionHeartbeat')._meta[NS].facts.uptime_ms, 60000);
  assert.equal(hook('TurnStarted').turnId, '1');
  assert.equal(hook('UserPromptQueued')._meta[NS].facts.prompt_id, 'synthetic-prompt');
  assert.equal(records.filter(r => r.type === 'session_info' && r.endedAt).length, 1);
  assert.equal(records.filter(r => r.type === 'subagent').length, 0);
});

test('Kimi clipped output is marked at the native 2000 character boundary', t => {
  const { env, rows, text } = setup(t);
  for (const [callId, length] of [['short', 1999], ['bounded', 2000]]) {
    const payload = { session_id: 'synthetic-boundary', tool_call_id: callId, hook_event_name: 'PostToolUse', tool_output: 'x'.repeat(length) };
    assert.equal(record('kimi-code', adapt('kimi-code', payload), { env }), true);
  }
  assert.deepEqual(rows().filter(r => r.type === 'tool_result').map(r => r.truncated), [undefined, true]);
  assert.equal(validate(text()).valid, true);
});

test('Kimi 2.x uses shared privacy rules and keeps unlinked decisions without invented subjects', t => {
  const { env, text, rows } = setup(t);
  const send = payload => assert.equal(record('kimi-code', adapt('kimi-code', {
    session_id: 'synthetic-kimi-privacy', ...payload,
  }), { env }), true);
  for (const secret of secretCases()) {
    send({ hook_event_name: 'UserPromptSubmit', prompt: [{ type: 'text', text: secret }] });
    send({ hook_event_name: 'PostToolUseFailure', error: { message: secret, code: secret } });
  }
  send({ hook_event_name: 'PermissionResult', tool_name: 'shell', decision: 'approved', scope: 'session' });
  const captured = text();
  for (const secret of secretCases()) assert.equal(captured.includes(JSON.stringify(secret).slice(1, -1)), false);
  assert.ok(rows().some(row => row.missing?.includes('redacted_content')));
  const approval = rows().find(row => row.type === 'approval');
  assert.equal(approval.decision, 'approved');
  assert.equal(approval.scope, 'session');
  assert.equal('subject' in approval, false);
  assert.equal('callId' in approval, false);
  assert.equal(validate(captured).valid, true);
});

test('Kimi legacy and 2.x configurations remain separate and both bundles execute', async t => {
  const { root, env, rows, text } = setup(t);
  const names = text => [...text.matchAll(/^event = "([^"]+)"$/gm)].map(match => match[1]);
  assert.deepEqual(names(configuration('kimi-code')), events['kimi-code']);
  assert.deepEqual(names(configuration('kimi-code', { kimiVersion: 2 })), kimiV2Events);
  assert.equal(kimiV2Events.length, 20);
  assert.ok(!events['kimi-code'].includes('PermissionResult'));
  const target = await buildPlugin('kimi-code', join(root, "bundle with 'quotes"));
  for (const filename of ['hooks.toml', 'hooks-v2.toml']) {
    const config = readFileSync(join(target, filename), 'utf8');
    const command = JSON.parse(config.match(/^command = (.+)$/m)[1]);
    const run = spawnSync('/bin/sh', ['-c', command], { encoding: 'utf8', cwd: root,
      env: { ...process.env, ...env }, input: JSON.stringify({ session_id: 'synthetic-bundle', hook_event_name: 'UserPromptSubmit', prompt: [{ type: 'text', text: filename }] }) });
    assert.equal(run.status, 0); assert.equal(run.stdout, ''); assert.equal(run.stderr, '');
  }
  assert.equal(rows().filter(r => r.type === 'message').length, 2);
  assert.equal(validate(text()).valid, true);
});

test('Mux bundled MCP server records with the manifest host environment allowlist', async t => {
  const { root, env, text } = setup(t);
  const target = await buildPlugin('mux', join(root, 'plugin'));
  const config = JSON.parse(readFileSync(join(target, '.mcp.json'), 'utf8'));
  const host = { ...env, PROVIDER_API_KEY: 'synthetic-provider-credential' };
  const forwarded = Object.fromEntries(config.mcpServers['asr-recorder'].env_vars.map(name => [name, host[name]]));
  assert.equal(forwarded.PROVIDER_API_KEY, undefined);
  const input = JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'observe',
    arguments: { session_id: 'synthetic-mcp-host', hook_event_name: 'UserPromptSubmit', prompt: 'synthetic forwarded content' } } }) + '\n';
  const run = spawnSync(process.execPath, [join(target, 'server.mjs')], { input, env: forwarded, encoding: 'utf8' });
  assert.equal(run.status, 0); assert.equal(run.stderr, '');
  assert.equal(JSON.parse(run.stdout).result.content[0].text, '{}');
  assert.ok(text().includes('synthetic forwarded content'));
  assert.equal(validate(text()).valid, true);
});
