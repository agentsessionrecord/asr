import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, rmSync, readFileSync, readdirSync, mkdirSync, cpSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';
import { agents, buildPlugin } from '../build.mjs';
import { validate } from '../../../tools/validator/src/index.js';

for (const agent of agents) test(`${agent}: standalone installation runs without checkout imports`, async t => {
  const root = mkdtempSync(join(tmpdir(), 'asr-package-')); t.after(() => rmSync(root, { recursive: true, force: true }));
  const target = await buildPlugin(agent, join(root, 'installed'));
  const output = join(root, 'out'); mkdirSync(output, { mode: 0o700 });
  const env = { ...process.env, ASR_OUTPUT_DIR: output, ASR_CONTENT: 'full' };
  if (['pi', 'amp'].includes(agent)) {
    const previous = { output: process.env.ASR_OUTPUT_DIR, content: process.env.ASR_CONTENT };
    process.env.ASR_OUTPUT_DIR = output; process.env.ASR_CONTENT = 'full';
    try {
      const handlers = new Map(), plugin = (await import(pathToFileURL(join(target, 'index.mjs')))).default;
      await plugin({ on: (name, handler) => handlers.set(name, handler) });
      const result = agent === 'pi' ? handlers.get('session_start')({ type: 'session_start', reason: 'new' },
        { cwd: '/work/synthetic', sessionManager: { getSessionId: () => 'synthetic-packaged' } })
        : handlers.get('tool.call')({ thread: { id: 'synthetic-packaged' }, toolUseID: 'one', tool: 'Bash', input: {} });
      assert.deepEqual(result, agent === 'amp' ? { action: 'allow' } : undefined);
    } finally {
      for (const [key, value] of [['ASR_OUTPUT_DIR', previous.output], ['ASR_CONTENT', previous.content]]) {
        if (value === undefined) delete process.env[key]; else process.env[key] = value;
      }
    }
  } else {
    let input = readFileSync(new URL(`../../${agent}/fixtures/native.jsonl`, import.meta.url), 'utf8').split('\n')[0];
    if (agent === 'mux') input = JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'observe', arguments: JSON.parse(input) } }) + '\n';
    const program = join(target, agent === 'mux' ? 'server.mjs' : 'command.mjs');
    if (agent === 'cline') cpSync(join(target, 'hooks'), join(root, 'project/.cline/hooks'), { recursive: true });
    const run = agent === 'cline'
      ? spawnSync(join(root, 'project/.cline/hooks/TaskStart'), [], { input, env, encoding: 'utf8', cwd: root })
      : spawnSync(process.execPath, [program, agent], { input, env, encoding: 'utf8', cwd: root });
    assert.equal(run.status, 0, run.stderr);
    assert.equal(run.stderr, '');
    if (agent !== 'mux') assert.equal(run.stdout, '');
  }
  const files = readdirSync(output).filter(name => name.endsWith('.jsonl'));
  assert.equal(files.length, 1);
  assert.equal(validate(readFileSync(join(output, files[0]), 'utf8')).valid, true);
  await assert.rejects(buildPlugin(agent, target), /empty/);
});
