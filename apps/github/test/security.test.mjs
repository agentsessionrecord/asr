import assert from 'node:assert/strict';
import test from 'node:test';
import { Git } from '../dist/git.js';
import { setup } from './helpers.mjs';

test('Git reads ignore inherited routing and config and disable executable readers', t => {
  const source = setup(t);
  const injected = { GIT_DIR: '/unavailable/synthetic-repository', GIT_CONFIG_COUNT: '1',
    GIT_CONFIG_KEY_0: 'asr.injected', GIT_CONFIG_VALUE_0: 'synthetic' };
  const old = Object.fromEntries(Object.keys(injected).map(key => [key, process.env[key]]));
  try {
    Object.assign(process.env, injected);
    const git = new Git(source.directory);
    assert.equal(git.run(['rev-parse', 'HEAD']).trim(), source.head);
    assert.equal(git.run(['config', '--get', '--default', 'safe', 'asr.injected']).trim(), 'safe');
    assert.equal(git.run(['config', '--get', 'core.fsmonitor']).trim(), 'false');
    assert.equal(git.run(['config', '--get', 'log.showSignature']).trim(), 'false');
  } finally {
    for (const [key, value] of Object.entries(old)) if (value === undefined) delete process.env[key]; else process.env[key] = value;
  }
});
