import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { chmodSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { repositoryRoot } from '../lib/files.mjs';

const runner = path.join(repositoryRoot, 'plugins/opencode/scripts/live-test.mjs');

test('OpenCode runner reads a custom endpoint, model and credential from private settings', t => {
  const root = mkdtempSync(path.join(tmpdir(), 'asr-provider-test-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const observed = path.join(root, 'observed.json');
  const binary = path.join(root, 'synthetic-agent');
  const key = path.join(root, 'key');
  writeFileSync(key, 'synthetic-credential', { mode: 0o600 });
  writeFileSync(binary, `#!/usr/bin/env node
const fs = require('node:fs');
const file = process.env.OPENCODE_CONFIG;
const config = JSON.parse(fs.readFileSync(file));
const provider = config.provider.asr_test;
fs.writeFileSync(${JSON.stringify(observed)}, JSON.stringify({
  endpoint: provider.options.baseURL, model: config.model,
  permission: fs.statSync(file).mode & 0o777,
  credentialMatches: provider.options.apiKey === 'synthetic-credential',
  credentialInEnvironment: Object.values(process.env).includes('synthetic-credential'),
  selectedModel: process.argv[process.argv.indexOf('--model') + 1], settingsPath: file,
}));
`);
  chmodSync(binary, 0o700);
  const env = { PATH: process.env.PATH, ASR_OPENAI_BASE_URL: 'http://127.0.0.1:19321/v1',
    ASR_OPENAI_MODEL: 'synthetic-model', ASR_PROVIDER_KEY_FILE: key };
  const result = spawnSync(process.execPath, [runner, 'opencode', binary], { env, encoding: 'utf8' });
  // The stub inspects configuration and emits no capture, so the live assertions fail.
  assert.equal(result.status, 1, result.stderr);
  const { settingsPath, ...actual } = JSON.parse(readFileSync(observed));
  assert.deepEqual(actual, { endpoint: env.ASR_OPENAI_BASE_URL, model: 'asr_test/synthetic-model',
    permission: 0o600, credentialMatches: true, credentialInEnvironment: false,
    selectedModel: 'asr_test/synthetic-model' });
  assert.throws(() => readFileSync(settingsPath), /ENOENT/);
  assert.doesNotMatch(result.stdout + result.stderr, /synthetic-credential/);
});

test('OpenCode runner rejects non-loopback routes before reading any credential', () => {
  for (const endpoint of ['https://api.example.invalid/v1', 'http://127.0.0.1:0/v1',
    'http://localhost:19321/v1', 'http://user:synthetic@127.0.0.1:19321/v1']) {
    const result = spawnSync(process.execPath, [runner, 'opencode', '/missing-agent'], {
      env: { PATH: process.env.PATH, ASR_OPENAI_BASE_URL: endpoint, ASR_OPENAI_MODEL: 'synthetic-model',
        ASR_PROVIDER_KEY_FILE: '/missing-credential' }, encoding: 'utf8',
    });
    assert.equal(result.status, 1);
    assert.match(result.stderr, /explicit_loopback_endpoint_required/);
    assert.doesNotMatch(result.stderr, /ENOENT/);
  }
});
