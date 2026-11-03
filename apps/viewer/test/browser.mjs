import assert from 'node:assert/strict';
import { readdir, readFile, mkdtemp, rm, writeFile, mkdir, open, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { chromium } from 'playwright';

const root = fileURLToPath(new URL('../../../', import.meta.url));
const scratch = await mkdtemp(path.join(tmpdir(), 'asr-viewer-test-'));
const evidence = process.env.ASR_VIEWER_EVIDENCE_DIR;
if (evidence) await mkdir(evidence, { recursive: true });
const executablePath = process.env.ASR_VIEWER_CHROMIUM || process.env.CHROME;
const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
const context = await browser.newContext({ viewport: { width: 1440, height: 1050 } });
const page = await context.newPage();
page.setDefaultTimeout(15000);
const errors = [], network = [];
page.on('pageerror', error => errors.push(error.message));
await context.route(/^https?:/, route => { network.push(route.request().url()); return route.abort(); });
const metrics = { files: 0, jsonlFiles: 0, knownRecords: 0, screenshots: [], browser: browser.version() };
const header = { type: 'session', id: 'header', formatVersion: '0.1', agent: { name: 'com.example.agent' }, sessionId: 'test', producer: { name: 'fixture', version: '1', method: 'native' } };
const coreTypes = new Set(['session', 'session_info', 'message', 'tool_call', 'tool_result', 'approval', 'file_change', 'vcs', 'inference', 'gap', 'annotation']);
const writeSession = async (name, records) => {
  const file = path.join(scratch, name);
  await writeFile(file, records.map(r => typeof r === 'string' ? r : JSON.stringify(r)).join('\n') + '\n');
  return file;
};
function validate(file) {
  const result = spawnSync(process.execPath, [path.join(root, 'tools/validator/bin/asr-validate.js'), file], { cwd: root, encoding: 'utf8', maxBuffer: 1024 * 1024 });
  assert.equal(result.status, 0, 'Generated synthetic session must validate without errors');
}
async function filesUnder(dir) {
  const files = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...await filesUnder(file)); else files.push(file);
  }
  return files.sort();
}
async function load(files) {
  await page.locator('#files').setInputFiles(files);
  await page.waitForFunction(() => document.body.dataset.state === 'ready', { timeout: 120000 });
  assert.equal(await page.locator('#facts').isVisible(), true);
}
async function jump(line, id) {
  await page.locator('#line').fill(String(line)); await page.locator('#go').click();
  await page.waitForFunction(({ line, id }) => [...document.querySelectorAll('.record')].some(e => e.dataset.index === String(line - 1) && (id === undefined || e.dataset.record === id)), { line, id });
  return page.locator(`.record[data-index="${line - 1}"]`);
}

try {
  await page.goto(new URL('../dist/index.html', import.meta.url).href);
  assert.equal(await page.title(), 'ASR session viewer');
  assert.equal(await page.locator('#welcome').isVisible(), true);
  const files = [...await filesUnder(path.join(root, 'samples')), ...await filesUnder(path.join(root, 'examples'))];
  for (const file of files) {
    await load(file); metrics.files++;
    if (!file.endsWith('.jsonl')) {
      assert.match(await page.locator('#facts').innerText(), /not an ASR JSONL/);
      continue;
    }
    metrics.jsonlFiles++;
    const lines = (await readFile(file, 'utf8')).split('\n').slice(0, -1);
    assert.match(await page.locator('#record-count').innerText(), new RegExp(`^${lines.length}`));
    for (let i = 0; i < lines.length; i++) {
      let r; try { r = JSON.parse(lines[i]); } catch { continue; }
      if (!coreTypes.has(r.type) || typeof r.id !== 'string') continue;
      const card = await jump(i + 1, r.id); metrics.knownRecords++;
      assert.equal(await card.getAttribute('data-type'), r.type);
      if (r.type === 'message' && r.content?.some?.(p => p.type === 'text')) assert.match(await card.innerText(), /author|origin/);
      if (r.type === 'file_change') assert.match(await card.innerText(), /diff|replacement|state|touched/i);
      if (r.type === 'inference') assert.match(await card.innerText(), /Served model|SERVED MODEL/i);
    }
    const sample = /samples\/(claude-code|codex)\/asr\/session\.jsonl$/.exec(file);
    if (sample && evidence) {
      const target = lines.findIndex(line => { const r = JSON.parse(line); return r.type === 'tool_call'; });
      await jump(Math.max(1, target + 1));
      const name = `${sample[1]}.png`;
      await page.screenshot({ path: path.join(evidence, name) }); metrics.screenshots.push(name);
    }
  }
  console.log(`PASS all ${metrics.files} sample/example files (${metrics.jsonlFiles} JSONL), ${metrics.knownRecords} known records`);

  // The folder picker resolves parent and child links using only opened files.
  await page.locator('#folder').setInputFiles(path.join(root, 'examples/subagent'));
  await page.waitForFunction(() => document.body.dataset.state === 'ready');
  assert.equal(await page.locator('.session').count(), 2);
  const parentButton = page.locator('.session').filter({ hasText: 'parent.jsonl' });
  await parentButton.click();
  const childLink = page.locator('#facts button').filter({ hasText: 'child (subagent)' });
  assert.equal(await childLink.count(), 1); await childLink.click();
  await page.waitForFunction(() => document.querySelector('#facts')?.textContent?.includes('child-1'));
  await jump(2, 'inherited');
  assert.equal(await page.locator('.record[data-record="inherited"]').getAttribute('data-copy'), 'true');
  console.log('PASS folder picker, bidirectional subagent links, copied-prefix markers');

  const forkParent = await writeSession('fork-parent.jsonl', [{ ...header, sessionId: 'root:7' }, { type: 'message', id: 'prompt #7', role: 'user', content: [] }]);
  const forkChild = await writeSession('fork-child.jsonl', [{ ...header, sessionId: 'fork', parent: { session: 'com.example.agent:root%3A7', kind: 'fork', record: 'prompt #7', copiedThrough: 'inherited' } }, { type: 'message', id: 'inherited', role: 'user', content: [] }]);
  validate(forkParent); validate(forkChild);
  await load([forkParent, forkChild]);
  await page.locator('.session').filter({ hasText: 'fork-child.jsonl' }).click();
  await page.locator('#facts button').filter({ hasText: 'parent (fork)' }).click();
  await page.waitForFunction(() => [...document.querySelectorAll('.record')].some(e => e.dataset.record === 'prompt #7'));
  await load(forkChild);
  assert.match(await page.locator('#facts').innerText(), /unresolved, file not opened/);
  console.log('PASS fork links, encoded session identity, opaque record IDs and unresolved files');

  const annotation = { type: 'annotation', kind: 'title', session: 'com.example.agent:root%3A7', source: { name: 'fixture' }, data: { title: 'Synthetic later title' } };
  const older = await writeSession('one.annotations.jsonl', [{ ...annotation, id: 'a', at: '2030-01-01T00:00:00.000001Z' }]);
  const newer = await writeSession('two.annotations.jsonl', [{ ...annotation, id: 'b', at: '2030-01-01T00:00:00.000002Z' }]);
  validate(older); validate(newer); await load([forkParent, older, newer]);
  const titleLinks = page.locator('#facts button').filter({ hasText: 'Later title:' });
  assert.equal(await titleLinks.count(), 1); await titleLinks.click();
  assert.match(await page.locator('.session[aria-current="true"]').innerText(), /two.annotations.jsonl/);
  assert.match(await (await jump(1, 'b')).innerText(), /Current later fact/);
  await page.locator('.session').filter({ hasText: 'one.annotations.jsonl' }).click();
  assert.match(await (await jump(1, 'a')).innerText(), /Historical or unfamiliar later fact/);
  console.log('PASS annotations join targets across files and retain timestamp precision');

  // Drops exercise the same public UI as a local file picker.
  const minimal = await readFile(path.join(root, 'examples/minimal.jsonl'), 'utf8');
  await page.evaluate(text => {
    const transfer = new DataTransfer(); transfer.items.add(new File([text], 'drop.jsonl', { type: 'application/jsonl' }));
    document.dispatchEvent(new DragEvent('drop', { dataTransfer: transfer, bubbles: true, cancelable: true }));
  }, minimal);
  await page.waitForFunction(() => document.body.dataset.state === 'ready' && document.querySelector('#facts')?.textContent?.includes('minimal-1'));
  console.log('PASS drag and drop');

  const hostile = await writeSession('untrusted.jsonl', [
    { ...header, title: '<img src="https://example.invalid/image" onerror="window.__asrInjected=1">' },
    { type: 'message', id: 'attack', role: 'user', author: 'human', origin: 'prompt', content: [
      { type: 'text', text: '<script>window.__asrInjected=1;fetch("https://example.invalid/run")</script>' },
      { type: 'resource_link', name: 'untrusted', uri: 'https://example.invalid/resource' },
      { type: 'resource', resource: { uri: 'javascript:window.__asrInjected=1', text: '<iframe src="https://example.invalid/frame"></iframe>' } },
      { type: 'image', mimeType: 'image/svg+xml', data: 'PHN2Zy8+' },
    ] },
    { type: 'tool_call', id: 'call', callId: 'c', name: 'shell', inputText: 'original input' },
    { type: 'session_info', id: 'settings', agentSettings: { approval: false, asks: 'never', modelSettings: { temperature: 0 } }, tools: [] },
    { type: 'approval', id: 'approval', callId: 'c', decision: 'approved', by: 'policy' },
    { type: 'tool_result', id: 'result', callId: 'c', status: 'completed', inputText: '', exec: { exitCode: 0 } },
    { type: 'file_change', id: 'diff', path: '/work/file.txt', op: 'modify', status: 'applied', patch: '--- a/file\n+++ b/file\n-old\n+<script>window.__asrInjected=1</script>\n' },
    { type: 'inference', id: 'model', model: { requested: 'alias' }, usage: { inputTokens: 0, outputTokens: 0 }, cost: { amount: 0, currency: 'USD' } },
    { type: 'gap', id: 'gap', reason: 'redacted', count: 0 },
    { type: 'vcs', id: 'pr', action: 'pr_link', status: 'completed', evidence: 'reported', pr: { url: 'javascript:window.__asrInjected=1' } },
    '{"type":"tool_call","id":"exact","callId":"unresolved","name":"noop","input":{"number":9007199254740993,"fraction":1.23000000000000001}}',
  ]);
  validate(hostile); await load(hostile);
  assert.match(await (await jump(2, 'attack')).innerText(), /<script>/);
  assert.equal(await page.locator('img,iframe,a[href],object,embed').count(), 0);
  assert.equal(await page.evaluate(() => window.__asrInjected), undefined);
  const callCard = await jump(3, 'call');
  assert.match(await callCard.innerText(), /Paired by unique call ID/);
  assert.equal(await callCard.getByRole('button', { name: 'Approval', exact: true }).count(), 1);
  assert.match(await callCard.innerText(), /Effective input learned at completion/i);
  const diffCard = await jump(7, 'diff'); assert.equal(await diffCard.locator('.diff .added').count(), 2);
  assert.match(await (await jump(11, 'exact')).innerText(), /9007199254740993/);
  await (await jump(11, 'exact')).getByRole('button', { name: 'Read record', exact: true }).click();
  await page.locator('#detail').waitFor({ state: 'visible' });
  await page.locator('#detail details').evaluate(e => e.open = true);
  assert.match(await page.locator('#raw').innerText(), /1\.23000000000000001/);
  await page.locator('#close-detail').click();
  assert.equal(network.length, 0);
  console.log('PASS untrusted text, resources, patches, exact numbers, approvals and effective input, no URI requests');

  // Malformed records are intentional negative fixtures, not generated valid ASR.
  const broken = await writeSession('broken.jsonl', [header, '{broken', { type: 'message', id: 'survives', role: 'assistant', content: [] }]);
  await writeFile(broken, '{"type":"message","id":"tail","role":"user","content":[]}', { flag: 'a' });
  await load(broken);
  assert.match(await (await jump(2)).innerText(), /Malformed complete line/);
  assert.match(await (await jump(4)).innerText(), /Incomplete final line/);
  await jump(3, 'survives');
  console.log('PASS malformed-line recovery and incomplete-tail deferral');

  // A large fixture tests the actual File/worker/DOM path, not an in-memory mock.
  const large = path.join(scratch, 'large.jsonl'), handle = await open(large, 'w');
  const payload = 'synthetic text '.repeat(850);
  let bytes = 0, count = 0;
  await handle.write(JSON.stringify({ ...header, sessionId: 'large' }) + '\n');
  while (bytes < 220 * 1024 * 1024) {
    const text = JSON.stringify({ type: 'message', id: `m-${count++}`, role: 'assistant', author: 'model', content: [{ type: 'text', text: payload }] }) + '\n';
    await handle.write(text); bytes += Buffer.byteLength(text);
  }
  await handle.close(); validate(large);
  await page.evaluate(() => { window.__heartbeat = 0; window.__lastBeat = performance.now(); window.__maxLag = 0; window.__timer = setInterval(() => { const now = performance.now(); window.__maxLag = Math.max(window.__maxLag, now - window.__lastBeat); window.__lastBeat = now; window.__heartbeat++; }, 20); });
  const started = performance.now(); await load(large);
  const last = await jump(count + 1, `m-${count - 1}`); assert.match(await last.innerText(), /synthetic text/);
  const perf = await page.evaluate(() => { clearInterval(window.__timer); return { heartbeats: window.__heartbeat, maxHeartbeatGapMs: Math.round(window.__maxLag), domRecords: document.querySelectorAll('.record').length }; });
  metrics.largeFile = { bytes: (await stat(large)).size, records: count + 1, loadAndLastRecordMs: Math.round(performance.now() - started), ...perf };
  assert.ok(perf.heartbeats > 10, 'Main-thread heartbeat must continue during parsing');
  assert.ok(perf.maxHeartbeatGapMs < 1000, 'No one-second UI freeze');
  assert.ok(perf.domRecords < 20, 'Timeline DOM must stay virtualized');
  console.log(`PASS large file: ${JSON.stringify(metrics.largeFile)}`);

  // Browser layout limits must not make late records unreachable.
  const many = path.join(scratch, 'many.jsonl');
  const manyLines = Array.from({ length: 100000 }, (_, i) => JSON.stringify({ type: 'message', id: `short-${i}`, role: 'assistant', content: [] })).join('\n');
  await writeFile(many, JSON.stringify(header) + '\n' + manyLines + '\n'); validate(many);
  await load(many); await jump(100001, 'short-99999');
  assert.ok(await page.locator('.record').count() < 20);
  console.log('PASS virtual scroll reaches record 100001');
  assert.deepEqual(errors, [], 'No uncaught page errors');
  assert.deepEqual(network, [], 'No network requests');
  if (evidence) await writeFile(path.join(evidence, 'browser-results.json'), JSON.stringify(metrics, null, 2) + '\n');
} finally {
  await context.close(); await browser.close(); await rm(scratch, { recursive: true, force: true });
}
