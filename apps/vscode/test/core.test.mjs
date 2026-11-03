import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, readFile, writeFile, copyFile, symlink, readdir } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { fixture, validateFixture } from './fixture.mjs';
import core from '../dist/core.cjs';
const { blame, parseExact, parseReport, reportText, findSession, sessionFiles, sessionReference, sessionCommand, viewerHtml, validateSettings } = core;
const root = fileURLToPath(new URL('../../../', import.meta.url));
const cli = process.env.ASR_EDITOR_CLI || path.join(root, 'target/debug/asr');

async function temporary(run) {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'asr-editor-test-'));
  try { return await run(dir, await fixture(dir)); } finally { await rm(dir, { recursive: true, force: true }); }
}
test('real CLI separates edit and commit evidence with model, prompt, approvals and losses', async () => temporary(async (dir, f) => {
  const report = await blame({ executable: cli, sessions: [f.store], annotations: [] }, f.repo, f.file, 1);
  assert.equal(report.editStatus, 'matched');
  assert.equal(report.editedBy[0].session, f.reference); assert.equal(report.committedBy[0].session, f.reference);
  assert.match(reportText(report), /synthetic-served/); assert.match(reportText(report), /9007199254740993/);
  assert.deepEqual(new Set(report.sessions[0].missing), new Set(['usage', 'approvals']));
  assert.equal(report.sessions[0].gaps[0].reason, 'not_recorded');
  assert.equal((await blame({ executable: cli, sessions: [f.store], annotations: [] }, f.repo, f.file, 2)).editStatus, 'unknown');
  await writeFile(f.file, 'unsaved on disk\n');
  assert.equal((await blame({ executable: cli, sessions: [f.store], annotations: [] }, f.repo, f.file, 1)).editStatus, 'unknown');
}));
test('copied edit and commit records never become this session credit', async () => temporary(async (dir, f) => {
  const lines = (await readFile(f.session, 'utf8')).trimEnd().split('\n');
  const header = JSON.parse(lines[0]); header.sessionId = 'copy';
  const copies = lines.slice(1).map(line => line.replace(/^\{/, '{"copiedFrom":' + JSON.stringify({ session: f.reference, record: parseExact(line).id }) + ','));
  await writeFile(f.session, [JSON.stringify(header), ...copies].join('\n') + '\n');
  validateFixture(f.session);
  const report = await blame({ executable: cli, sessions: [f.store], annotations: [] }, f.repo, f.file, 1);
  assert.deepEqual(report.editedBy, []); assert.deepEqual(report.committedBy, []);
}));
test('references resolve locally and ambiguous stores and symlinks fail closed', async () => temporary(async (dir, f) => {
  assert.equal(sessionReference({ type: 'session', formatVersion: '0.1', agent: { name: 'com.example.agent' }, namespace: 'a:#%', sessionId: 'x y\t\u0085' }), 'com.example.agent:a%3A%23%25:x%20y%09%C2%85');
  assert.equal(await findSession([f.store], f.reference + '#change'), f.session);
  await symlink(f.session, path.join(f.store, 'symlink.jsonl'));
  assert.deepEqual(await sessionFiles([f.store]), [f.session]);
  await assert.rejects(findSession([f.store], 'com.example.agent:missing'), /unresolved/);
  await copyFile(f.session, path.join(f.store, 'duplicate.jsonl'));
  await assert.rejects(findSession([f.store], f.reference), /ambiguous/);
}));
test('exact numeric tokens, open fields, invalid settings and cancelled processes', async () => temporary(async (dir, f) => {
  assert.deepEqual(parseExact('{"big":9007199254740993,"zero":0,"empty":"","flag":false,"value":1e999,"escaped":"\\\"123"}'), { big: '9007199254740993', zero: '0', empty: '', flag: false, value: '1e999', escaped: '"123' });
  assert.throws(() => parseReport('{}'), /Unsupported/);
  const command = sessionCommand('com.example.agent:)[open](https://example.invalid)');
  assert.ok(!command.includes('(') && !command.includes(')'));
  assert.deepEqual(JSON.parse(decodeURIComponent(command.split('?')[1])), ['com.example.agent:)[open](https://example.invalid)']);
  assert.throws(() => validateSettings({ executable: cli, sessions: ['relative'], annotations: [] }), /absolute/);
  const controller = new AbortController(); controller.abort();
  await assert.rejects(blame({ executable: cli, sessions: [f.store], annotations: [] }, f.repo, f.file, 1, controller.signal), /cancelled/);
  await assert.rejects(blame({ executable: path.join(dir, 'missing'), sessions: [f.store], annotations: [] }, f.repo, f.file, 1), /failed/);
}));
test('all sample and example streams pass through the real blame reader', async () => temporary(async (dir, f) => {
  let count = 0;
  async function walk(dir) {
    for (const item of await readdir(dir, { withFileTypes: true })) {
      const file = path.join(dir, item.name);
      if (item.isDirectory()) await walk(file);
      else if (item.name.endsWith('.jsonl') && !item.name.endsWith('.annotations.jsonl')) {
        const header = JSON.parse((await readFile(file, 'utf8')).split('\n')[0]);
        if (header.type !== 'session') continue;
        const report = await blame({ executable: cli, sessions: [file], annotations: [] }, f.repo, f.file, 1);
        assert.deepEqual(report.editedBy, []); assert.deepEqual(report.committedBy, []); count++;
      }
    }
  }
  await walk(path.join(root, 'samples')); await walk(path.join(root, 'examples'));
  assert.ok(count >= 17); console.log(`Corpus streams checked: ${count}`);
}));
test('bundled viewer opens exact local bytes and hostile content makes no requests', async () => temporary(async (dir, f) => {
  const require = createRequire(new URL('../../viewer/package.json', import.meta.url));
  const { chromium } = require('playwright');
  const template = await readFile(new URL('../dist/viewer.html', import.meta.url), 'utf8');
  const html = await viewerHtml(template, f.session);
  assert.ok(!html.includes('<script>globalThis.injected'));
  assert.match(html, /connect-src 'none'/);
  const output = path.join(dir, 'viewer.html'); await writeFile(output, html);
  const browser = await chromium.launch({ headless: true, ...(process.env.CHROME ? { executablePath: process.env.CHROME } : {}) });
  try {
    const page = await browser.newPage(); const requests = []; const errors = [];
    page.on('request', r => { if (/^https?:/.test(r.url())) requests.push(r.url()); });
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(pathToFileURL(output).href);
    await page.waitForFunction(() => document.body.dataset.state === 'ready');
    assert.equal(await page.locator('#file-count').textContent(), '1');
    assert.equal(await page.evaluate(() => globalThis.injected), undefined);
    assert.deepEqual(requests, []); assert.deepEqual(errors, []);
  } finally { await browser.close(); }
}));
