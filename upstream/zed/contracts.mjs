import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { privacyFindings } from '../../scripts/check-privacy.mjs';
import { checkWriting } from '../../scripts/check-writing.mjs';
import { validateFile } from '../../tools/validator/src/index.js';

const directory = dirname(fileURLToPath(import.meta.url));
const root = resolve(directory, '../..');
const metadata = JSON.parse(readFileSync(join(directory, 'manifest.json'), 'utf8')).provenance;
assert.match(metadata.base, /^[a-f0-9]{40}$/);
assert.match(metadata.commit, /^[a-f0-9]{40}$/);
const patch = readFileSync(join(directory, metadata.patch), 'utf8');
assert.ok(patch.startsWith(`From ${metadata.commit} `));
assert.match(patch, /method/);
const parsed = spawnSync('git', ['apply', '--numstat', join(directory, metadata.patch)], { encoding: 'utf8' });
assert.equal(parsed.status, 0, parsed.stderr);
const prose = readFileSync(join(directory, 'PROPOSAL.md'), 'utf8');
assert.deepEqual(checkWriting(prose, 'PROPOSAL.md'), []);
for (const [file, digest] of Object.entries(metadata.files)) {
  assert.equal(createHash('sha256').update(readFileSync(join(directory, file))).digest('hex'), digest, file);
}
for (const file of readdirSync(directory, { recursive: true }).filter((file) => !file.endsWith('/') && /\.(?:patch|md|jsonl?|sql|native|py|mjs)$/.test(file))) {
  assert.deepEqual(privacyFindings(readFileSync(join(directory, file), 'utf8')), [], file);
}
for (const file of readdirSync(directory).filter((name) => name.endsWith('.jsonl'))) {
  const result = validateFile(join(directory, file));
  assert.equal(result.valid, true, JSON.stringify(result.diagnostics));
  const source = readFileSync(join(directory, file), 'utf8');
  const header = JSON.parse(source.split('\n')[0]);
  assert.equal(header.agent.name, metadata.agent);
  assert.equal(header.producer.method, 'native');
  assert.ok(header.missing.length > 0);
  assert.ok(!source.includes('opaque-synthetic-state'));
  assert.ok(!source.includes('synthetic-excluded-signature'));
  assert.ok(!source.includes('excluded-synthetic-value'));
  assert.ok(!source.includes('"endedAt"'));
  const cli = spawnSync(process.execPath, ['tools/validator/bin/asr-validate.js', '--summary', join(directory, file)], { cwd: root, encoding: 'utf8' });
  assert.equal(cli.status, 0, cli.stdout + cli.stderr);
  process.stdout.write(cli.stdout);
}

const sample = readFileSync(join(directory, 'samples/asr/session.jsonl'), 'utf8').trimEnd().split('\n').map((line) => JSON.parse(line));
const messages = sample.filter((record) => record.type === 'message');
const calls = sample.filter((record) => record.type === 'tool_call');
const results = sample.filter((record) => record.type === 'tool_result');
if (['zed', 'forgecode', 'shelley'].includes(metadata.agent)) {
  assert.equal(calls.length, 1);
  assert.equal(results.length, 1);
  assert.equal(calls[0].callId, results[0].callId);
  assert.equal(calls[0].input.number, '9007199254740993');
  assert.equal(calls[0].inputText, undefined);
  const reasoning = messages.flatMap(record => record.content).find(part => part.type === 'reasoning' && part.visibility === 'summary');
  assert.ok(reasoning.summary.length);
  assert.equal(reasoning.text, undefined);
}
if (metadata.agent === 'warp') {
  assert.equal(messages[0].id, '9007199254740993');
  assert.equal(messages[0].content[0].text, 'Read the synthetic item.\n');
  assert.ok(sample.some((record) => record.type === 'gap'));
}
if (metadata.agent === 'zed') assert.ok(sample.some((record) => record.reason === 'not_retained'));
if (metadata.agent === 'forgecode') assert.equal(messages[0].author, undefined);
if (metadata.agent === 'shelley') {
  assert.equal(results[0].status, 'failed');
  assert.ok(sample.findIndex((record) => record.id === 'notice') < sample.findIndex((record) => record.type === 'tool_result'));
}
if (metadata.agent === 'nanoclaw') {
  assert.equal(messages[0].id, '9007199254740993');
  assert.ok(messages[0].ts > messages[1].ts);
  assert.equal(messages[0].author, undefined);
}
if (metadata.agent === 'fx') assert.equal(messages[0].content[0].text, 'CONV_FIRST 1');

console.log(`${metadata.agent}: patch structure, privacy, prose and sample contracts passed.`);
