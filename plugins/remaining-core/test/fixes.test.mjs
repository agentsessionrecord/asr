import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { once } from 'node:events';
import { appendFileSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { test } from 'node:test';
import { record as remaining } from '../recorder.mjs';
import { record as gemini } from '../../gemini-qwen-core/recorder.mjs';
import { secretCases, ordinaryFields } from '../../../packages/writer/test/secret-cases.mjs';
import { captureSession } from '../../../packages/writer/dist/capture.js';

let validated = 0;
const warnings = {};
function harness(t, core) {
  const directory = mkdtempSync(join(tmpdir(), 'asr-fix-test-'));
  t.after(() => {
    try {
      for (const name of readdirSync(directory).filter(name => name.endsWith('.jsonl'))) {
        const result = spawnSync(process.execPath, ['tools/validator/bin/asr-validate.js', '--json', join(directory, name)], { encoding: 'utf8' });
        const report = JSON.parse(result.stdout);
        assert.equal(report.errors, 0, JSON.stringify(report.counts));
        assert.equal(result.status, 0);
        validated++;
        for (const [code, count] of Object.entries(report.counts)) warnings[code] = (warnings[code] ?? 0) + count;
      }
    } finally { rmSync(directory, { recursive: true, force: true }); }
  });
  const send = (event = {}) => core === 'remaining'
    ? remaining('goose', { sessionId: 'synthetic', event: 'fixture', ...event }, { env: { ASR_OUTPUT_DIR: directory, ASR_CONTENT: 'full' }, now: '2026-11-01T00:00:00Z' })
    : gemini('qwen-code', { session_id: 'synthetic', hook_event_name: 'Notification', ...event }, { directory, full: true, knownSecrets: [], now: () => '2026-11-01T00:00:00Z' });
  const path = () => join(directory, readdirSync(directory).find(name => name.endsWith('.jsonl')));
  return { directory, send, path, rows: () => readFileSync(path(), 'utf8').trimEnd().split('\n').map(JSON.parse),
    start: () => send(core === 'remaining' ? { start: true, fresh: true } : { hook_event_name: 'SessionStart', source: 'startup' }),
    lock: () => core === 'remaining' ? path().replace('.jsonl', '.lock') : path() + '.lock',
    state: () => core === 'remaining' ? path().replace('.jsonl', '.state') : path() + '.state',
    cli: core === 'remaining' ? [resolve('plugins/remaining-core/command.mjs'), 'goose'] : [resolve('plugins/qwen-code/dist/record.mjs'), 'qwen-code'] };
}

for (const core of ['remaining', 'gemini']) {
  test(`${core}: a killed lock holder is recovered and its loss precedes new observations`, async t => {
    const h = harness(t, core);
    assert.equal(h.start(), true);
    const prefix = readFileSync(h.path());
    const helper = new URL('../../../packages/writer/dist/capture.js', import.meta.url).href;
    const child = spawn(process.execPath, ['--input-type=module', '-e', `import { acquireCaptureLock } from ${JSON.stringify(helper)}; const lock = acquireCaptureLock(process.argv[1]); process.send(!!lock); setInterval(() => {}, 1000);`, h.lock()], { stdio: ['ignore', 'ignore', 'inherit', 'ipc'] });
    t.after(() => { if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL'); });
    assert.deepEqual(await once(child, 'message'), [true, undefined]);
    const dead = once(child, 'exit');
    child.kill('SIGKILL'); await dead;
    assert.equal(h.send(), true);
    assert.deepEqual(readFileSync(h.path()).subarray(0, prefix.length), prefix);
    const rows = h.rows();
    assert.equal(rows.filter(row => row.type === 'gap').length, 1);
    assert.ok(rows.findIndex(row => row.type === 'gap') < rows.findLastIndex(row => row.type.endsWith('/hook')));
    assert.ok(rows.some(row => row.missing?.includes('dropped_callbacks')));
    assert.equal(h.send(), true);
  });

  test(`${core}: expired lock metadata is recovered`, t => {
    const h = harness(t, core); h.start();
    writeFileSync(h.lock(), JSON.stringify({ pid: process.pid, createdAt: Date.now() - 11000 }), { mode: 0o600 });
    assert.equal(h.send(), true);
    assert.equal(h.rows().filter(row => row.type === 'gap').length, 1);
  });

  test(`${core}: older checkpoints seal without mixing extension conventions`, t => {
    const h = harness(t, core); h.start();
    const state = JSON.parse(readFileSync(h.state())); delete state.captureVersion;
    writeFileSync(h.state(), JSON.stringify(state));
    const prefix = readFileSync(h.path());
    assert.equal(h.send(), false);
    assert.deepEqual(readFileSync(h.path()).subarray(0, prefix.length), prefix);
    assert.equal(h.rows().at(-2).type, 'gap');
  });

  for (const failure of ['missing', 'malformed', 'mismatch', 'oversized']) test(`${core}: ${failure} checkpoint appends one sealing gap`, t => {
    const h = harness(t, core); h.start();
    const prefix = readFileSync(h.path());
    if (failure === 'missing') rmSync(h.state());
    else if (failure === 'malformed') writeFileSync(h.state(), '{');
    else if (failure === 'oversized') writeFileSync(h.state(), 'x'.repeat(2 * 1024 * 1024 + 1));
    else { const state = JSON.parse(readFileSync(h.state())); state.size = (state.size ?? state.bytes) + 1; writeFileSync(h.state(), JSON.stringify(state)); }
    assert.equal(h.send(), false);
    assert.deepEqual(readFileSync(h.path()).subarray(0, prefix.length), prefix);
    assert.equal(h.rows().at(-2).type, 'gap');
    assert.ok(h.rows().at(-1).missing.includes('capture_stopped'));
    const sealed = readFileSync(h.path());
    assert.equal(h.send(), false);
    assert.deepEqual(readFileSync(h.path()), sealed);
  });

  test(`${core}: oversized event records a gap and later events still append`, t => {
    const h = harness(t, core); h.start();
    const text = 'x'.repeat(1024 * 1024 + 1);
    assert.equal(h.send(core === 'remaining' ? { message: { role: 'user', content: text } } : { hook_event_name: 'AfterAgent', prompt_response: text }), true);
    assert.equal(h.send(), true);
    assert.equal(h.rows().filter(row => row.type === 'gap').length, 1);
    assert.equal(h.rows().at(-1).type.endsWith('/hook'), true);
  });

  test(`${core}: oversized command input leaves a loss for the next callback`, t => {
    const h = harness(t, core); h.start();
    const run = spawnSync(process.execPath, h.cli, { input: 'x'.repeat(1024 * 1024 + 1), encoding: 'utf8', env: { PATH: process.env.PATH, ASR_OUTPUT_DIR: h.directory }, maxBuffer: 1024 * 1024 });
    assert.equal(run.status, 0); assert.equal(run.stdout, ''); assert.equal(run.stderr, '');
    assert.equal(h.send(), true);
    assert.equal(h.rows().filter(row => row.type === 'gap').length, 1);
  });

  test(`${core}: stdin deadline leaves a loss and keeps the hook fail open`, async t => {
    const h = harness(t, core); h.start();
    const child = spawn(process.execPath, h.cli, { env: { PATH: process.env.PATH, ASR_OUTPUT_DIR: h.directory }, stdio: ['pipe', 'pipe', 'pipe'] });
    let stdout = '', stderr = '';
    child.stdout.on('data', bytes => { stdout += bytes; }); child.stderr.on('data', bytes => { stderr += bytes; });
    const closed = once(child, 'close');
    child.stdin.write('{');
    assert.deepEqual(await closed, [0, null]);
    assert.equal(stdout, ''); assert.equal(stderr, '');
    assert.equal(h.send(), true);
    assert.equal(h.rows().filter(row => row.type === 'gap').length, 1);
  });

  test(`${core}: all shared credential cases redact without changing token counts`, t => {
    const h = harness(t, core);
    for (const secret of secretCases()) {
      h.send(core === 'remaining' ? { message: { role: 'user', content: secret }, facts: ordinaryFields }
        : { hook_event_name: 'AfterAgent', prompt_response: secret, tool_input: ordinaryFields });
    }
    const data = readFileSync(h.path(), 'utf8');
    for (const secret of secretCases()) assert.equal(data.includes(JSON.stringify(secret).slice(1, -1)), false);
    const metadata = h.rows().find(row => row._meta)?._meta['org.agentsessionrecord.hooks'];
    assert.deepEqual(core === 'remaining' ? metadata.facts : metadata.tool_input, ordinaryFields);
  });

  test(`${core}: secret-shaped property names are excluded`, t => {
    const h = harness(t, core), secret = secretCases()[1];
    h.send(core === 'remaining' ? { facts: { [secret]: 'synthetic value', ...ordinaryFields } }
      : { tool_input: { [secret]: 'synthetic value', ...ordinaryFields } });
    assert.equal(readFileSync(h.path(), 'utf8').includes(secret), false);
  });

  test(`${core}: an approval without a native subject keeps only the stated decision`, t => {
    const h = harness(t, core);
    h.send(core === 'remaining' ? { approval: { decision: 'denied' }, name: 'shell' } : { hook_event_name: 'PermissionDenied', tool_name: 'shell' });
    const approval = h.rows().find(row => row.type === 'approval');
    assert.equal(approval.decision, 'denied'); assert.equal('subject' in approval, false); assert.equal('callId' in approval, false);
    h.send(core === 'remaining' ? { approval: { decision: 'approved', subject: '' } } : { hook_event_name: 'PermissionDenied', subject: '' });
    assert.equal(h.rows().filter(row => row.type === 'approval').at(-1).subject, '');
  });
}

for (const agent of ['gemini-cli', 'qwen-code']) for (const source of ['resume', undefined, 'startup', 'clear']) test(`${agent}: first session event source ${source} has only sourced starting facts`, t => {
  const h = harness(t, 'gemini');
  assert.equal(gemini(agent, { session_id: 'synthetic', hook_event_name: 'SessionStart', ...(source === undefined ? {} : { source }), cwd: '/work/synthetic' }, { directory: h.directory, full: true, knownSecrets: [] }), true);
  const rows = h.rows(), original = ['startup', 'clear'].includes(source);
  assert.equal('startedAt' in rows[0], original);
  assert.equal('cwd' in rows[0], original);
  assert.equal(rows[0].missing.includes('history_before_capture'), !original);
  assert.equal(rows[1].type === 'gap', !original);
});

for (const agent of ['gemini-cli', 'qwen-code']) test(`${agent}: a first tool callback marks earlier history and does not establish a start time`, t => {
  const h = harness(t, 'gemini');
  assert.equal(gemini(agent, { session_id: 'synthetic', hook_event_name: agent === 'gemini-cli' ? 'BeforeTool' : 'PreToolUse', tool_use_id: 'synthetic-call', tool_name: 'shell' }, { directory: h.directory, full: true, knownSecrets: [] }), true);
  assert.equal('startedAt' in h.rows()[0], false);
  assert.equal(h.rows()[1].type, 'gap');
});

for (const limit of ['stream', 'state', 'deadline']) test(`shared storage seals before crossing the ${limit} limit`, t => {
  const h = harness(t, 'remaining'); h.start();
  const prefix = readFileSync(h.path());
  const ts = '2026-11-01T00:00:01Z';
  assert.equal(captureSession({ directory: h.directory, agent: 'goose', sessionId: 'synthetic', path: h.path(), statePath: h.state(), lockPath: h.lock(), ts,
    header: h.rows()[0], initial: { size: 0, position: 1 }, maxState: limit === 'state' ? 16 : 1024 * 1024,
    ...(limit === 'stream' ? { maxStream: prefix.length + 1 } : {}),
    project() {
      if (limit === 'deadline') Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 660);
      return [{ type: 'message', role: 'user', content: [] }];
    },
  }), false);
  assert.deepEqual(readFileSync(h.path()).subarray(0, prefix.length), prefix);
  assert.equal(h.rows().at(-2).type, 'gap');
});

test('torn history retains every byte and records a local loss when no valid gap can be appended', t => {
  const h = harness(t, 'remaining'); h.start();
  const valid = readFileSync(h.path()); appendFileSync(h.path(), '{');
  const torn = readFileSync(h.path());
  assert.equal(h.send(), false); assert.deepEqual(readFileSync(h.path()), torn);
  assert.ok(readdirSync(h.directory).some(name => name.endsWith('.dropped')));
  // Injected torn bytes are not completed recorder output. Validate the unchanged complete prefix.
  writeFileSync(h.path(), valid);
});

test.after(() => console.log(JSON.stringify({ regressionStreams: validated, warnings })));
