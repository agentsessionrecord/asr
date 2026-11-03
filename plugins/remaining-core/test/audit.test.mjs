import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, writeFileSync, appendFileSync, readdirSync, readFileSync, rmSync, truncateSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout } from 'node:timers/promises';
import { validate } from '../../../tools/validator/src/index.js';
import { follow } from '../../cline/tail-audit.mjs';

function setup(t, initial = '') {
  const root = mkdtempSync(join(tmpdir(), 'asr-audit-test-'));
  const path = join(root, 'hooks.jsonl'), output = join(root, 'output');
  writeFileSync(path, initial);
  const controller = new AbortController();
  const following = follow(path, { signal: controller.signal, env: { ASR_OUTPUT_DIR: output, ASR_CONTENT: 'full' } });
  // Attach a rejection observer before deliberately malformed bytes are appended.
  following.catch(() => {});
  t.after(async () => { controller.abort(); await following.catch(() => {}); rmSync(root, { recursive: true, force: true }); });
  const text = () => readFileSync(join(output, readdirSync(output).find(name => name.endsWith('.jsonl'))), 'utf8');
  return { path, text, following };
}

const prompt = text => JSON.stringify({ taskId: 'synthetic-session', hookName: 'prompt_submit', userPromptSubmit: { prompt: text } });
async function until(check) {
  const deadline = Date.now() + 3000;
  while (Date.now() < deadline) {
    try { if (check()) return; } catch {}
    await setTimeout(10);
  }
  assert.fail('Audit follower did not produce the expected observation');
}

test('Cline audit starts at EOF and skips a partial preexisting line', async t => {
  const stale = prompt('stale-partial');
  const { path, text } = setup(t, prompt('stale-complete') + '\n' + stale.slice(0, 20));
  appendFileSync(path, stale.slice(20) + '\n' + prompt('fresh') + '\n');
  await until(() => text().includes('fresh'));
  assert.ok(!text().includes('stale'));
  assert.equal(validate(text()).valid, true);
  assert.equal(text().trimEnd().split('\n').map(JSON.parse).filter(r => r.type === 'message').length, 1);
});

test('Cline audit preserves split UTF-8 bytes and waits for the final newline', async t => {
  const { path, text } = setup(t);
  const prefix = Buffer.byteLength(prompt('')) - 3;
  const content = 'x'.repeat(65535 - prefix) + '雪🙂';
  const bytes = Buffer.from(prompt(content));
  assert.equal(bytes[65535], 0xe9);
  appendFileSync(path, bytes.subarray(0, 65536));
  await setTimeout(150);
  appendFileSync(path, bytes.subarray(65536));
  await setTimeout(150);
  assert.throws(text);
  appendFileSync(path, '\n');
  await until(() => text().includes('雪🙂'));
  const message = text().trimEnd().split('\n').map(JSON.parse).find(r => r.type === 'message');
  assert.equal(message.content[0].text, content);
  assert.equal(validate(text()).valid, true);
});

test('Cline audit stops on malformed input without consuming later records', async t => {
  const { path, text, following } = setup(t);
  appendFileSync(path, '{malformed}\n' + prompt('unobserved') + '\n');
  await assert.rejects(following, SyntaxError);
  assert.throws(text);
});

test('Cline audit stops on truncation', async t => {
  const { path, following } = setup(t, prompt('stale') + '\n');
  truncateSync(path, 0);
  await assert.rejects(following, /truncated/);
});
