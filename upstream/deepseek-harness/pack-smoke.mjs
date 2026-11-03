import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
const directory = fileURLToPath(new URL('./plugin/', import.meta.url));
const scratch = mkdtempSync(join(tmpdir(), 'dsh-asr-pack-'));
const run = (args, cwd) => {
  const result = spawnSync('npm', args, { cwd, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stdout + result.stderr);
  return result.stdout;
};
try {
  const [packed] = JSON.parse(run(['pack', '--json', '--pack-destination', scratch], directory));
  const files = packed.files.map(item => item.path);
  for (const required of ['dist/index.js', 'dist/index.d.ts', 'dist/format.js', 'cordis.patch.yml', 'README.md', 'LICENSE']) assert.ok(files.includes(required), required);
  assert.ok(!files.some(name => /node_modules|test\.mjs|package-lock/.test(name)));
  writeFileSync(join(scratch, 'package.json'), '{"private":true,"type":"module","overrides":{"zod":"4.6.6"}}\n');
  run(['install', '--ignore-scripts', '--omit=dev', '--no-audit', '--no-fund', join(scratch, packed.filename)], scratch);
  run(['audit', '--omit=dev'], scratch);
  const smoke = spawnSync(process.execPath, ['--input-type=module', '-e', "import { Context } from '@deepseek-ai/cordis'; import * as plugin from 'dsh-plugin-asr-export'; if (!Context || plugin.route !== '/api/session.asr') throw new Error('invalid package'); const text = plugin.formatAgentSession({ id: 'synthetic', createdAt: 1 }, [], 0); if (JSON.parse(text).agent.name !== 'deepseek-harness') throw new Error('invalid export');"], { cwd: scratch, encoding: 'utf8' });
  assert.equal(smoke.status, 0, smoke.stdout + smoke.stderr);
  console.log(`deepseek-harness: npm pack and fresh production install passed (${files.length} package files)`);
} finally { rmSync(scratch, { recursive: true, force: true }); }
