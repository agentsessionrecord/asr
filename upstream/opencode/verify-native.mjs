import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';

// Run with Bun against the pinned upstream source checkout, without a model.
const checkout = process.argv[2];
assert.ok(checkout, 'usage: bun verify-native.mjs UPSTREAM_CHECKOUT');
const directory = path.dirname(fileURLToPath(import.meta.url));
const agent = path.basename(directory);
const module = await import(pathToFileURL(path.resolve(checkout, "packages/cli/src/agent-session.ts")).href);
const input = await readFile(path.join(directory, "samples/native/native.json"), 'utf8');
const emit = (value) => agent === 'opencode'
  ? module.records('ses_synthetic', value).map((record) => JSON.stringify(record)).join('\n') + '\n'
  : agent === 'kilo'
    ? module.records('ses_synthetic', value, 'test').map((record) => JSON.stringify(record)).join('\n') + '\n'
    : agent === 'cline' ? module.exportAgentSession('synthetic-session', value)
      : module.exportSession(value);
const scratch = await mkdtemp(path.join(tmpdir(), 'asr-native-refresh-'));
try {
  const stream = emit(JSON.parse(input));
  const output = path.join(scratch, 'session.jsonl');
  await writeFile(output, stream, { mode: 0o600 });
  execFileSync('node', [path.resolve(directory, '../../tools/validator/bin/asr-validate.js'), '--summary', output], { stdio: 'inherit' });
  assert.equal(stream, await readFile(path.join(directory, 'samples/asr/session.jsonl'), 'utf8'));
  
  console.log(`${agent}: native fixture export, validator and exact sample replay passed`);
} finally {
  await rm(scratch, { recursive: true, force: true });
}
