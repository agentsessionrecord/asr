import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { Git } from '../src/git.ts';
import { loadStore } from '../src/reader.ts';
import { asBytes, header, setup } from './helpers.mjs';

test('Git routing, executable readers and inherited config do not change the chosen repository', t => {
  const source = setup(t);
  const injected = { GIT_DIR: '/unavailable/synthetic-repository', GIT_CONFIG_COUNT: '1',
    GIT_CONFIG_KEY_0: 'asr.injected', GIT_CONFIG_VALUE_0: 'synthetic' };
  const old = Object.fromEntries(Object.keys(injected).map(key => [key, process.env[key]]));
  try {
    Object.assign(process.env, injected);
    const git = new Git(source.repo);
    assert.equal(git.run(['rev-parse', 'HEAD']).trim(), source.base);
    assert.equal(git.run(['config', '--get', '--default', 'safe', 'asr.injected']).trim(), 'safe');
    assert.equal(git.run(['config', '--get', 'core.fsmonitor']).trim(), 'false');
    assert.equal(git.run(['config', '--get', 'log.showSignature']).trim(), 'false');
  } finally {
    for (const [key, value] of Object.entries(old)) if (value === undefined) delete process.env[key]; else process.env[key] = value;
  }
});

test('local store limits reject excessive bytes, files and nesting', t => {
  const source = setup(t), store = path.join(source.directory, 'store');
  mkdirSync(store);
  const bytes = asBytes([header()]);
  writeFileSync(path.join(store, 'one.jsonl'), bytes);
  const limits = { depth: 4, files: 10, fileBytes: 1024, totalBytes: 2048 };
  assert.equal(loadStore(store, limits).sessions.length, 1);
  assert.throws(() => loadStore(store, { ...limits, fileBytes: bytes.length - 1 }), /size limit/);
  assert.throws(() => loadStore(store, { ...limits, totalBytes: bytes.length - 1 }), /byte limit/);
  writeFileSync(path.join(store, 'two.jsonl'), bytes);
  assert.throws(() => loadStore(store, { ...limits, files: 1 }), /file limit/);
  mkdirSync(path.join(store, 'nested'));
  assert.throws(() => loadStore(store, { ...limits, depth: 0 }), /nesting limit/);
});
