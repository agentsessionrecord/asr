import assert from 'node:assert/strict';
import { mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync, statSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { execFileSync } from 'node:child_process';
import { test } from 'node:test';
import { Recorder, META } from '../dist/recorder.js';
import { snapshot } from '../dist/privacy.js';
import { Sink } from '../dist/sink.js';
import { secretCases, ordinaryFields } from '../../../packages/writer/test/secret-cases.mjs';

const trace = JSON.parse(readFileSync(new URL('./fixtures/legacy.json', import.meta.url)));
const validator = resolve('../../tools/validator/bin/asr-validate.js');
const event = (type, properties) => ({ event: { type, properties } });
const created = id => event('session.created', { info: { id } });
let streams = 0;
let records = 0;
const diagnostics = {};

function harness(t, options = {}) {
  const directory = mkdtempSync(join(tmpdir(), 'asr-plugin-test-'));
  let tick = 0;
  const recorder = new Recorder({ agent: 'opencode', directory, content: 'full', secrets: [], now: () => new Date(1793534400000 + tick++).toISOString(), ...options });
  t.after(() => {
    recorder.close();
    for (const file of readdirSync(directory).filter(file => file.endsWith('.jsonl'))) {
      const path = join(directory, file);
      const result = JSON.parse(execFileSync(process.execPath, [validator, '--json', path], { encoding: 'utf8' }));
      assert.equal(result.errors, 0, JSON.stringify(result));
      streams++;
      records += readFileSync(path, 'utf8').trimEnd().split('\n').length;
      for (const diagnostic of result.diagnostics ?? []) diagnostics[diagnostic.code] = (diagnostics[diagnostic.code] ?? 0) + 1;
    }
    rmSync(directory, { recursive: true, force: true });
  });
  return { recorder, directory, read() {
    recorder.flush();
    return readdirSync(directory).filter(file => file.endsWith('.jsonl')).flatMap(file => readFileSync(join(directory, file), 'utf8').trimEnd().split('\n').map(JSON.parse));
  } };
}

for (const agent of ['opencode', 'kilo', 'mimocode']) {
  test(`${agent}: receipt order, final arguments, terminal output and one result`, t => {
    const h = harness(t, { agent });
    const original = JSON.stringify(trace);
    for (const item of trace) h.recorder.observe(item.name, item.input, item.output);
    assert.equal(JSON.stringify(trace), original);
    let rows = h.read();
    const published = readFileSync(new URL(`./fixtures/streams/${agent}.jsonl`, import.meta.url), 'utf8').trimEnd().split('\n').map(JSON.parse);
    assert.deepEqual(rows, published);
    assert.equal(rows[0].agent.name, agent);
    assert.equal(rows[0].producer.method, 'recorder');
    assert.equal(rows[0].startedAt, '2026-11-01T12:00:00.000Z');
    const call = rows.find(row => row.type === 'tool_call');
    assert.equal(call.callId, 'call-1');
    assert.equal(call.input, undefined);
    assert.equal(call._meta[META].requestedInput.command, 'printf requested');
    const result = rows.find(row => row.type === 'tool_result');
    assert.deepEqual(result.input, { command: 'printf effective', workdir: '/work/synthetic' });
    assert.equal(result.content[0].text, 'effective\n');
    assert.equal(result.durationMs, 15);
    assert.equal(result.exec.exitCode, 0);
    assert.ok(rows.findIndex(row => row.hook === 'session.status') < rows.indexOf(result));
    const approval = rows.find(row => row.type === 'approval');
    assert.equal(approval.decision, 'approved');
    assert.equal(approval.scope, 'once');
    assert.equal(approval.by, undefined);
    assert.ok(rows.indexOf(approval) < rows.indexOf(result));
    assert.ok(!rows.some(row => 'endedAt' in row));
    h.recorder.observe(trace[7].name, trace[7].input);
    rows = h.read();
    assert.equal(rows.filter(row => row.type === 'tool_result').length, 1);
  });
}

test('request and provisional permission hook state do not invent approvals', t => {
  const h = harness(t);
  h.recorder.observe('event', created('s'));
  h.recorder.observe('permission.ask', { sessionID: 's' }, { status: 'allow' });
  h.recorder.observe('event', event('permission.asked', { sessionID: 's', id: 'ask', permission: 'network' }));
  assert.equal(h.read().filter(row => row.type === 'approval').length, 0);
  h.recorder.observe('event', event('permission.replied', { sessionID: 's', requestID: 'ask', reply: 'reject' }));
  const approval = h.read().find(row => row.type === 'approval');
  assert.equal(approval.decision, 'denied');
  assert.equal(approval.subject, 'network');
  assert.equal(approval.by, undefined);
  assert.equal(approval.scope, undefined);
});

test('always replies leave lifetime and decider unknown', t => {
  const h = harness(t);
  h.recorder.observe('event', created('s'));
  h.recorder.observe('event', event('permission.replied', { sessionID: 's', requestID: 'unseen', reply: 'always' }));
  const approval = h.read().find(row => row.type === 'approval');
  assert.equal(approval.decision, 'approved');
  assert.equal(approval.by, undefined);
  assert.equal(approval.scope, undefined);
  assert.equal('subject' in approval, false);
});

test('Mimocode cancellation is an explicit outcome without a guessed approval', t => {
  const h = harness(t, { agent: 'mimocode' });
  h.recorder.observe('event', created('s'));
  h.recorder.observe('tool.execute.before', { sessionID: 's', callID: 'c', tool: 'bash' }, { args: {}, cancel: true, cancelReason: 'synthetic cancellation' });
  h.recorder.observe('event', event('message.part.updated', { part: { type: 'tool', sessionID: 's', callID: 'c', tool: 'bash', state: { status: 'completed', input: {}, output: 'synthetic cancellation', metadata: { cancelled: true } } } }));
  const rows = h.read();
  assert.equal(rows.find(row => row.type === 'tool_result').status, 'cancelled');
  assert.ok(!rows.some(row => row.type === 'approval'));
});

test('failure comes from native status and is not derived from an exit code', t => {
  const h = harness(t);
  h.recorder.observe('event', created('s'));
  for (const [callID, status, exit] of [['a', 'completed', 4], ['b', 'error', 0]]) {
    h.recorder.observe('event', event('message.part.updated', { part: { type: 'tool', sessionID: 's', callID, tool: 'bash', state: { status, input: {}, output: '', error: 'synthetic error', metadata: { exit } } } }));
  }
  const results = h.read().filter(row => row.type === 'tool_result');
  assert.deepEqual(results.map(row => row.status), ['completed', 'failed']);
  assert.deepEqual(results.map(row => row.exec.exitCode), [4, 0]);
});

test('late executed arguments win over an earlier request retained in the terminal part', t => {
  const h = harness(t);
  const copied = structuredClone(trace);
  copied[7].input.event.properties.part.state.input = { command: 'printf requested' };
  for (const item of copied) h.recorder.observe(item.name, item.input, item.output);
  const result = h.read().find(row => row.type === 'tool_result');
  assert.equal(result.input.command, 'printf effective');
  assert.equal(result.exec.command, 'printf effective');
});

test('metadata mode omits content but keeps outcomes and native identity', t => {
  const h = harness(t, { content: 'metadata' });
  for (const item of trace) h.recorder.observe(item.name, item.input, item.output);
  const rows = h.read();
  assert.equal(rows[0].sessionId, 'synthetic-session');
  assert.ok(rows[0].missing.includes('content'));
  assert.ok(!JSON.stringify(rows).includes('printf'));
  assert.equal(rows.find(row => row.type === 'tool_result').status, 'completed');
  assert.equal(rows.find(row => row.type === 'tool_result').truncated, true);
});

test('known credentials are excluded, source text stays exact otherwise', t => {
  const h = harness(t, { secrets: ['synthetic-confidential-value'] });
  const copied = structuredClone(trace);
  copied[7].input.event.properties.part.state.output = ' a\r\nb  \nsynthetic-confidential-value';
  copied[7].input.event.properties.part.state.input.apiKey = 'synthetic-confidential-value';
  for (const item of copied) h.recorder.observe(item.name, item.input, item.output);
  const rows = h.read();
  assert.ok(!JSON.stringify(rows).includes('synthetic-confidential-value'));
  const result = rows.find(row => row.type === 'tool_result');
  assert.equal(result.content[0].text, ' a\r\nb  \n[redacted]');
  assert.equal(result.truncated, true);
});

test('restarts append the same file, retain pairing and never rewrite its prefix', t => {
  const h = harness(t);
  for (const item of trace.slice(0, 6)) h.recorder.observe(item.name, item.input, item.output);
  h.recorder.close();
  const file = readdirSync(h.directory).find(file => file.endsWith('.jsonl'));
  const prefix = readFileSync(join(h.directory, file));
  const resumed = new Recorder({ agent: 'opencode', directory: h.directory, content: 'full', secrets: [] });
  for (const item of trace.slice(6)) resumed.observe(item.name, item.input, item.output);
  resumed.close();
  const bytes = readFileSync(join(h.directory, file));
  assert.deepEqual(bytes.subarray(0, prefix.length), prefix);
  assert.equal(readdirSync(h.directory).filter(file => file.endsWith('.jsonl')).length, 1);
  const rows = bytes.toString().trimEnd().split('\n').map(JSON.parse);
  assert.equal(rows.filter(row => row.type === 'session').length, 1);
  assert.equal(rows.filter(row => row.type === 'tool_call').length, 1);
  assert.equal(rows.filter(row => row.type === 'tool_result').length, 1);
  assert.equal(new Set(rows.map(row => row.id)).size, rows.length);
  assert.equal(statSync(join(h.directory, file)).mode & 0o777, 0o600);
});

test('locked sessions fail open and keep the active writer intact', t => {
  const h = harness(t);
  h.recorder.observe('event', created('s'));
  h.read();
  const contender = new Recorder({ agent: 'opencode', directory: h.directory });
  contender.observe('event', created('s'));
  assert.doesNotThrow(() => contender.close());
  assert.equal(readdirSync(h.directory).filter(file => file.endsWith('.lock')).length, 1);
  h.recorder.observe('chat.message', { sessionID: 's', agent: 'build' });
  assert.ok(h.read().some(row => row.agentSettings?.mode === 'build'));
});

test('partial existing files fail open without modifying them', t => {
  const h = harness(t);
  h.recorder.observe('event', created('s'));
  h.recorder.close();
  const file = join(h.directory, readdirSync(h.directory).find(file => file.endsWith('.jsonl')));
  const prefix = readFileSync(file, 'utf8');
  writeFileSync(file, prefix + '{');
  const resumed = new Recorder({ agent: 'opencode', directory: h.directory });
  resumed.observe('event', created('s'));
  assert.doesNotThrow(() => resumed.close());
  assert.equal(readFileSync(file, 'utf8'), prefix + '{');
  // This is injected corruption, not recorder output. Restore the intact prefix for output validation.
  writeFileSync(file, prefix);
});

test('resume adds losses when content capture changes', t => {
  const h = harness(t);
  h.recorder.observe('event', created('s'));
  h.recorder.close();
  const resumed = new Recorder({ agent: 'opencode', directory: h.directory, content: 'metadata' });
  resumed.observe('chat.message', { sessionID: 's', agent: 'build' });
  resumed.close();
  assert.ok(h.read().some(row => row.type === 'session_info' && row.missing?.includes('content')));
});

test('resume rejects duplicate JSON keys instead of extending an invalid stream', t => {
  const h = harness(t);
  h.recorder.observe('event', created('s'));
  h.recorder.close();
  const file = join(h.directory, readdirSync(h.directory).find(file => file.endsWith('.jsonl')));
  const prefix = readFileSync(file, 'utf8');
  const corrupted = prefix + '{"type":"session_info","id":"bad","title":"first","title":"second"}\n';
  writeFileSync(file, corrupted);
  const recorder = new Recorder({ agent: 'opencode', directory: h.directory });
  recorder.observe('chat.message', { sessionID: 's', agent: 'build' });
  recorder.close();
  assert.equal(readFileSync(file, 'utf8'), corrupted);
  writeFileSync(file, prefix);
});

test('symlinked output directories are left untouched', t => {
  const h = harness(t);
  const link = join(h.directory, 'link');
  symlinkSync(h.directory, link);
  const recorder = new Recorder({ agent: 'opencode', directory: link });
  recorder.observe('event', created('s'));
  assert.doesNotThrow(() => recorder.close());
  assert.equal(readdirSync(h.directory).filter(name => name.endsWith('.jsonl')).length, 0);
});

test('bounded queue reports a gap and source objects can be frozen', t => {
  const h = harness(t, { maxQueue: 1 });
  h.recorder.observe('event', created('s'));
  h.recorder.observe('chat.message', Object.freeze({ sessionID: 's', agent: 'build' }));
  const rows = h.read();
  assert.ok(rows.some(row => row.type === 'gap'));
  assert.ok(rows.some(row => row.missing?.includes('dropped_callbacks')));
  assert.ok(rows.findIndex(row => row.hook === 'session.created') < rows.findIndex(row => row.type === 'gap'));
});

test('malformed callbacks, unsafe numbers and unwritable storage do not reject hooks', t => {
  const h = harness(t);
  assert.doesNotThrow(() => h.recorder.observe('event', null));
  assert.doesNotThrow(() => h.recorder.observe('tool.execute.before', { sessionID: 's' }, { args: { unsafe: 2 ** 54 } }));
  h.recorder.observe('event', created('s'));
  assert.ok(h.read().some(row => row.type === 'gap'));
  const path = join(h.directory, 'not-a-directory');
  writeFileSync(path, 'synthetic');
  const broken = new Recorder({ agent: 'opencode', directory: path });
  broken.observe('event', created('s'));
  assert.doesNotThrow(() => broken.close());
});

test('OpenCode V2 hooks and events use data, id and final content', t => {
  const h = harness(t);
  h.recorder.observe('event', { event: { type: 'session.created', data: { sessionID: 's', version: 'fixture-v2' } } });
  h.recorder.observe('v2.before', { sessionID: 's', id: 'c', tool: 'bash', agent: 'build', input: { command: 'requested' } });
  h.recorder.observe('event', { event: { type: 'permission.asked', data: { sessionID: 's', id: 'p', action: 'shell', source: { type: 'tool', id: 'c', messageID: 'm' } } } });
  h.recorder.observe('event', { event: { type: 'permission.replied', data: { sessionID: 's', requestID: 'p', reply: 'once' } } });
  h.recorder.observe('v2.after', { sessionID: 's', id: 'c', tool: 'bash', input: null, status: 'completed', result: { content: 'provisional' } });
  h.recorder.observe('event', { event: { id: 'native-terminal-event', type: 'session.tool.success', data: { sessionID: 's', id: 'c', executed: true, content: [{ type: 'text', text: '' }, { type: 'text', text: ' final\n' }] } } });
  const rows = h.read();
  const result = rows.find(row => row.type === 'tool_result');
  assert.equal(result.input, null);
  assert.equal(result.id, 'native-terminal-event');
  assert.deepEqual(result.content.map(part => part.text), ['', ' final\n']);
  assert.equal(rows.find(row => row.type === 'approval').callId, 'c');
});

test('plugin exports are passive, return promises and dispose safely', async t => {
  const h = harness(t);
  const previous = process.env.ASR_OUTPUT_DIR;
  process.env.ASR_OUTPUT_DIR = h.directory;
  t.after(() => { if (previous === undefined) delete process.env.ASR_OUTPUT_DIR; else process.env.ASR_OUTPUT_DIR = previous; });
  for (const entry of ['index', 'kilo', 'mimocode']) {
    const plugin = (await import(`../dist/${entry}.js`)).default;
    const hooks = await plugin({});
    const input = Object.freeze({ sessionID: entry, tool: 'bash', callID: 'c' });
    const output = Object.freeze({ args: Object.freeze({ command: 'synthetic' }) });
    await hooks.event(created(entry));
    assert.equal(await hooks['tool.execute.before'](input, output), undefined);
    await hooks.dispose();
  }
});

test('V2 setup registers passive domain hooks and cleans up its subscription', async t => {
  const h = harness(t);
  const previous = process.env.ASR_OUTPUT_DIR;
  process.env.ASR_OUTPUT_DIR = h.directory;
  t.after(() => { if (previous === undefined) delete process.env.ASR_OUTPUT_DIR; else process.env.ASR_OUTPUT_DIR = previous; });
  const hooks = new Map();
  let disposed = 0;
  let aborted = false;
  const hook = async (name, callback) => { hooks.set(name, callback); return { dispose: async () => { disposed++; } }; };
  const plugin = (await import('../dist/v2.js')).default;
  const cleanup = await plugin.setup({ tool: { hook }, permission: { hook }, event: { async *subscribe({ signal }) {
    signal.addEventListener('abort', () => { aborted = true; });
    yield { type: 'session.created', data: { sessionID: 'v2' } };
  } } });
  assert.deepEqual([...hooks.keys()], ['execute.before', 'execute.after', 'evaluate']);
  const before = Object.freeze({ sessionID: 'v2', id: 'c', tool: 'bash', input: Object.freeze({ command: 'synthetic' }) });
  assert.equal(hooks.get('execute.before')(before), undefined);
  hooks.get('execute.after')({ ...before, status: 'completed' });
  await cleanup();
  assert.equal(disposed, 3);
  assert.equal(aborted, true);
});

test('child creation records native association without guessing the relationship kind', t => {
  const h = harness(t);
  h.recorder.observe('event', event('session.created', { info: { id: 'child', parentID: 'parent' } }));
  const header = h.read()[0];
  assert.equal(header._meta[META].parentID, 'parent');
  assert.equal(header.parent, undefined);
  assert.ok(header.missing.includes('parent_lineage'));
});

test('snapshots preserve big native integers as strings and bound text', () => {
  const copied = snapshot({ input: { args: { native: 9007199254740993n, output: 'x'.repeat(200_000) } } }, true, []);
  assert.equal(copied.value.input.args.native, '9007199254740993');
  assert.equal(copied.shortened, true);
  assert.ok(copied.value.input.args.output.length <= 65536);
});

test('snapshot limits include object keys and exclude secrets in property names', () => {
  const secret = 'synthetic-private-field';
  const copied = snapshot({ input: { args: { [secret]: 'synthetic', ['x'.repeat(200_000)]: 'synthetic' } } }, true, [secret]);
  assert.equal(copied.shortened, true);
  assert.ok(!JSON.stringify(copied.value).includes(secret));
  assert.ok(Buffer.byteLength(JSON.stringify(copied.value)) < 128 * 1024);
});

test.after(() => {
  console.log(JSON.stringify({ validatedStreams: streams, validatedRecords: records, diagnostics }));
});


test('linked approvals omit a subject that merely names the tool permission', t => {
  const h = harness(t);
  for (const item of trace) h.recorder.observe(item.name, item.input, item.output);
  const approval = h.read().find(row => row.type === 'approval');
  assert.equal(approval.callId, 'call-1');
  assert.equal('subject' in approval, false);
});

test('shared secret forms redact while token counts remain intact', t => {
  const h = harness(t);
  h.recorder.observe('event', created('s'));
  for (const [index, secret] of secretCases().entries()) h.recorder.observe('event', event('message.part.updated', {
    part: { type: 'tool', sessionID: 's', callID: `secret-${index}`, tool: 'bash', state: { status: 'completed', input: ordinaryFields, output: secret } },
  }));
  const rows = h.read();
  for (const value of secretCases()) assert.equal(JSON.stringify(rows).includes(JSON.stringify(value).slice(1, -1)), false);
  assert.deepEqual(rows.find(row => row.type === 'tool_result').input, ordinaryFields);
});

test('subagent references preserve unreserved punctuation and encode reserved components once', t => {
  const h = harness(t);
  h.recorder.observe('event', created('s'));
  h.recorder.observe('event', event('message.part.updated', { part: { type: 'tool', sessionID: 's', callID: 'task', tool: 'task',
    state: { status: 'completed', output: '', metadata: { sessionId: 'child/a.b@c+é%:# ' } } } }));
  assert.equal(h.read().find(row => row.type === 'tool_result').subagent.session, 'opencode:child/a.b@c+é%25%3A%23%20');
});

test('a projection failure seals the stream with a gap before disabling capture', t => {
  const h = harness(t);
  h.recorder.observe('event', created('s')); h.read();
  const file = join(h.directory, readdirSync(h.directory).find(name => name.endsWith('.jsonl')));
  const prefix = readFileSync(file);
  h.recorder.observe('event', event('message.part.updated', { part: { type: 'tool', sessionID: 's', callID: 'bad', tool: 'bash',
    state: { status: 'completed', output: [{ type: 'text', text: 42 }] } } }));
  const rows = h.read();
  assert.equal(rows.at(-2).type, 'gap');
  assert.ok(rows.at(-1).missing.includes('capture_stopped'));
  assert.deepEqual(readFileSync(file).subarray(0, prefix.length), prefix);
  const stopped = readFileSync(file);
  h.recorder.observe('chat.message', { sessionID: 's', agent: 'build' }); h.read();
  assert.deepEqual(readFileSync(file), stopped);
});

test('unknown native parts use a vendor type beside known text parts', t => {
  const h = harness(t);
  h.recorder.observe('event', created('s'));
  h.recorder.observe('event', event('message.part.updated', { part: { type: 'tool', sessionID: 's', callID: 'native', tool: 'example',
    state: { status: 'completed', output: [{ type: 'document', title: 'Synthetic' }, { type: 'text', text: 'known' }] } } }));
  const content = h.read().find(row => row.type === 'tool_result').content;
  assert.deepEqual(content[0], { type: META + '/content', _meta: { [META]: { native: { type: 'document', title: 'Synthetic' } } } });
  assert.equal(content[1].text, 'known');
});

test('a resumed stream at the storage cap receives a sealing gap', t => {
  const h = harness(t);
  h.recorder.observe('event', created('s')); h.recorder.close();
  const file = join(h.directory, readdirSync(h.directory).find(name => name.endsWith('.jsonl')));
  const prefix = readFileSync(file, 'utf8') + JSON.stringify({ type: 'message', id: 'synthetic-large', role: 'user', content: [{ type: 'text', text: 'x'.repeat(16 * 1024 * 1024) }] }) + '\n';
  writeFileSync(file, prefix);
  const resumed = new Recorder({ agent: 'opencode', directory: h.directory });
  resumed.observe('chat.message', { sessionID: 's', agent: 'build' }); resumed.close();
  const bytes = readFileSync(file, 'utf8');
  assert.ok(bytes.startsWith(prefix));
  assert.equal(JSON.parse(bytes.trimEnd().split('\n').at(-2)).type, 'gap');
});

test('secret-valued native identities leave a loss instead of becoming join keys', t => {
  const secret = 'synthetic-confidential-value';
  const h = harness(t, { secrets: [secret] });
  h.recorder.observe('event', created(secret));
  assert.deepEqual(h.read(), []);
  h.recorder.observe('event', created('safe'));
  const rows = h.read();
  assert.equal(JSON.stringify(rows).includes(secret), false);
  assert.ok(rows.some(row => row.type === 'gap'));
  h.recorder.observe('tool.execute.before', { sessionID: 'safe', callID: secret, tool: 'bash' }, {});
  assert.equal(JSON.stringify(h.read()).includes(secret), false);
});


test('creation records repository facts and later observations keep the original header', t => {
  const h = harness(t);
  const repo = mkdtempSync(join(tmpdir(), 'asr-opencode-repo-'));
  t.after(() => rmSync(repo, { recursive: true, force: true }));
  execFileSync('git', ['-C', repo, 'init', '-q', '-b', 'initial']);
  h.recorder.observe('event', event('session.created', { info: { id: 's', directory: repo } }));
  const header = h.read()[0];
  assert.deepEqual(header.repos, [{ path: repo, branch: 'initial' }]);
  execFileSync('git', ['-C', repo, 'checkout', '-q', '-b', 'later']);
  h.recorder.observe('event', event('session.updated', { info: { id: 's', directory: repo } }));
  assert.deepEqual(h.read()[0], header);
});
