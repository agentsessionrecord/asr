import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { encodeReferenceComponent, sessionReference, environmentSecrets, credentialValues, isSecretKey, redactSecrets } from '../dist/index.js';
import { HOOK_CONVENTIONS } from '../dist/capture.js';
import { ordinaryFields, secretCases } from './secret-cases.mjs';

test('one reference encoder escapes only reserved characters with uppercase UTF-8 bytes', () => {
  assert.equal(encodeReferenceComponent('child/a.b@c+!é😀%:# \t\x7f\x85'), 'child/a.b@c+!é😀%25%3A%23%20%09%7F%C2%85');
  assert.equal(sessionReference('opencode', 'child/a@b', 'space #'), 'opencode:space%20%23:child/a@b');
  assert.throws(() => encodeReferenceComponent(''));
});

test('shared patterns exclude known token shapes and preserve ordinary token fields', () => {
  for (const value of secretCases()) assert.notEqual(redactSecrets(value), value);
  for (const key of Object.keys(ordinaryFields)) assert.equal(isSecretKey(key), false, key);
  for (const key of ['apiKey', 'api_key', 'access-token', 'refreshToken', 'auth_token', 'authorization', 'password', 'secret', 'cookie', 'private_key', 'client_secret', 'aws_secret_access_key']) assert.equal(isSecretKey(key), true, key);
  assert.deepEqual(environmentSecrets({ GIT_AUTHOR_NAME: 'Synthetic Author', TEST_API_KEY: 'synthetic-secret', MAX_TOKENS: 'ordinary-count', MONKEY: 'ordinary-word' }), ['synthetic-secret']);
  assert.equal(redactSecrets('max_tokens=42 inputTokens=10 tokens_used=3'), 'max_tokens=42 inputTokens=10 tokens_used=3');
});

test('every JavaScript core imports the shared convention and privacy helpers', () => {
  assert.equal(HOOK_CONVENTIONS.extension, 'org.agentsessionrecord.hooks/v1');
  for (const core of ['remaining-core', 'gemini-qwen-core', 'opencode/src']) {
    const file = new URL(`../../../plugins/${core}/recorder.${core.includes('opencode') ? 'ts' : 'mjs'}`, import.meta.url);
    const code = readFileSync(file, 'utf8');
    assert.ok(code.includes('HOOK_CONVENTIONS'));
    assert.ok(code.includes('environmentSecrets'));
    assert.doesNotMatch(code, /ASR_HOOKS_(?:DIR|CONTENT)|content_omitted|secret_redaction|message_text|org\.agentsessionrecord\.(?:opencode|recorder)/);
  }
});

test('credentials in serialized JSON, URL queries, Basic auth and unfinished private keys are scrubbed', () => {
  const value = 'synthetic-private-value';
  for (const key of ['api_key', 'apiKey', 'password', 'session_token', 'token', 'client_secret']) {
    assert.ok(!redactSecrets(JSON.stringify({ [key]: value })).includes(value));
    assert.ok(!redactSecrets(`${key}="${value} with spaces"`).includes(value));
    assert.equal(isSecretKey(key), true);
  }
  for (const text of [`https://${value}@example.invalid/repo`, `https://example.invalid/?token=${value}&public=yes`]) {
    assert.ok(!redactSecrets(text).includes(value));
  }
  const encoded = Buffer.from('synthetic-user:synthetic-password').toString('base64');
  assert.ok(!redactSecrets(`Basic ${encoded}`).includes(encoded));
  assert.equal(redactSecrets('Follow basic instructions.'), 'Follow basic instructions.');
  const partialKey = '-----BEGIN ' + 'PRIVATE KEY-----\n' + value;
  assert.ok(!redactSecrets(partialKey).includes(value));
  assert.equal(isSecretKey('set-cookie'), true);
});

test('named credentials are learned before sibling text and serialized JSON are scrubbed', () => {
  const value = 'synthetic-private-echo';
  for (const item of [{ password: value, text: value }, JSON.stringify({ api_key: value, text: value })]) {
    assert.ok(!redactSecrets(value, credentialValues(item)).includes(value));
  }
  assert.deepEqual(credentialValues({ token: '[redacted]' }), []);
});


test('Python and JavaScript distribute one versioned hook convention', () => {
  const python = JSON.parse(readFileSync(new URL('../../../python/agent_session_record/src/agent_session_record/hook-conventions.json', import.meta.url)));
  assert.deepEqual(HOOK_CONVENTIONS, python);
  for (const path of ['python/agent_session_record/src/agent_session_record/hooks.py', 'plugins/python-core/README.md', 'plugins/codex/README.md', 'plugins/python-core/tests/test_python_plugins.py', 'plugins/codex/fixtures/sample.jsonl']) {
    assert.doesNotMatch(readFileSync(new URL('../../../' + path, import.meta.url), 'utf8'), /org\.agentsessionrecord\.hooks\/hooks["`]/);
  }
});
