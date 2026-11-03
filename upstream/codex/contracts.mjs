import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const read = (name) => readFileSync(new URL(name, import.meta.url));
const manifest = JSON.parse(read('./manifest.json'));
const metadata = manifest.provenance;
const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');
assert.match(metadata.upstreamBase, /^[a-f0-9]{40}$/);
assert.match(metadata.implementationRevision, /^[a-f0-9]{40}$/);
assert.equal(manifest.patches.length, 6, 'core, settings, CLI, discovery, content naming and TUI integration are separate changes');
assert.deepEqual(metadata.patchSeries, manifest.patches.map(patch => patch.path));
for (const entry of manifest.patches) {
  const patch = read(`./${entry.path}`);
  assert.equal(sha256(patch), entry.sha256, 'patch integrity');
  assert.ok(patch.toString('utf8').startsWith(`From ${entry.commit} `));
  assert.doesNotMatch(patch.toString('utf8'), /^diff --git a\/.*\.md /m);
  assert.doesNotMatch(patch.toString('utf8'), /^diff --git a\/codex-rs\/session-export\/scripts\//m);
}
assert.equal(metadata.implementationRevision, manifest.head);
for (const [name, digest] of Object.entries(metadata.sampleFiles)) {
  assert.equal(sha256(read(`./${name}`)), digest, `sample integrity: ${name}`);
}
const file = fileURLToPath(new URL('./samples/asr/session.jsonl', import.meta.url));
const validator = fileURLToPath(new URL('../../tools/validator/bin/asr-validate.js', import.meta.url));
const validation = JSON.parse(execFileSync(process.execPath, [validator, '--json', file], { encoding: 'utf8' }));
assert.equal(validation.errors, 0, 'reference validation');
const records = read('./samples/asr/session.jsonl').toString('utf8').trimEnd().split('\n').map(JSON.parse);
assert.equal(records[0].producer.method, 'native');
const call = records.find((record) => record.type === 'tool_call');
const result = records.find((record) => record.type === 'tool_result');
const inference = records.find((record) => record.type === 'inference');
assert.equal(call.input.counter, '9007199254740993');
assert.equal(inference.usage.outputTokens, 0);
assert.ok(!Object.hasOwn(inference, 'model'));
assert.ok(!Object.hasOwn(inference.usage, 'inputTokens'));
assert.ok(records[0].missing.includes('model'));
const clear = records.find((record) => record.id === 'clear' || record.agentSettings?.approval === null);
assert.equal(clear.agentSettings.modelSettings.reasoningEffort, null);
assert.ok(records.indexOf(call) < records.findIndex((record) => record.id === 'notice'));
assert.ok(records.findIndex((record) => record.id === 'notice') < records.indexOf(result));
assert.deepEqual(records.map((record) => record.type), [
  'session', 'session_info', 'tool_call', 'message', 'tool_result', 'session_info', 'inference', 'message',
]);
assert.equal(result.input.counter, '18446744073709551617');
assert.equal(result.ts, '2026-10-31T12:00:03Z');
assert.equal(clear.agentSettings.approval, null);
assert.equal(clear.agentSettings.modelSettings.serviceTier, null);
assert.equal(inference._meta['com.openai.codex'].usageRecord.usage.input_tokens, '9007199254740993');
assert.deepEqual(records.at(-1).content, [
  { type: 'com.openai.codex/content', _meta: { 'com.openai.codex': { native: { type: 'document', name: 'notes.pdf' } } } },
  { type: 'text', text: 'Read these notes.' },
  { type: 'com.openai.codex/content', _meta: { 'com.openai.codex': { native: { type: 'refusal', refusal: 'Synthetic refusal.' } } } },
]);
assert.deepEqual(validation.counts, { 'warning:unknown-extension': 1 });
console.log('Codex package integrity and completion, settings, input, numeric and vendor content contracts passed.');
