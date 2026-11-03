import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';

const require = createRequire(new URL('../../apps/viewer/package.json', import.meta.url));
const { chromium } = require('playwright');
const files = process.argv.slice(2);
const browser = await chromium.launch({ headless: true, executablePath: process.env.ASR_VIEWER_CHROMIUM });
try {
  const context = await browser.newContext();
  const network = [], errors = [];
  await context.route(/^https?:/, route => { network.push(true); return route.abort(); });
  const page = await context.newPage();
  page.on('pageerror', () => errors.push(true));
  await page.goto(new URL('../../apps/viewer/dist/index.html', import.meta.url).href);
  assert.equal(await page.title(), 'ASR session viewer');
  await page.locator('#files').setInputFiles(files);
  await page.waitForFunction(() => document.body.dataset.state === 'ready');
  assert.equal(await page.locator('.session').count(), 3);
  let records = 0;
  for (const file of files) {
    const source = (await readFile(file, 'utf8')).trimEnd().split('\n').map(JSON.parse);
    await page.locator('.session').filter({ hasText: file.split('/').at(-1) }).click();
    await page.waitForFunction(session => document.querySelector('#facts').textContent.includes(session), source[0].sessionId);
    assert.match(await page.locator('#record-count').innerText(), new RegExp(`^${source.length}\\b`));
    // Check every record through the public line-jump control and worker path.
    for (const [index, row] of source.entries()) {
      await page.locator('#line').fill(String(index + 1));
      await page.locator('#go').click();
      const card = page.locator(`.record[data-index="${index}"]`);
      await page.waitForFunction(({ index, id }) => [...document.querySelectorAll('.record')]
        .some(element => element.dataset.index === String(index) && element.dataset.record === id), { index, id: row.id });
      assert.equal(await card.getAttribute('data-type'), row.type);
      if (row.type === 'message') {
        for (const part of row.content ?? []) {
          if (part.type === 'text' && /^ASR_E2E_[A-Z_]+_DONE\s*$/.test(part.text)) {
            assert.ok((await card.innerText()).includes(part.text.trim()));
          }
        }
      }
      records++;
    }
  }
  assert.deepEqual(errors, []);
  assert.deepEqual(network, []);
  console.log(JSON.stringify({ files: files.length, records, pageErrors: errors.length, networkRequests: network.length }));
  await context.close();
} finally {
  await browser.close();
}
