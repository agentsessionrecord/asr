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
assert.equal(manifest.patches.length, 8, 'source layers, fixtures, CLI, tests, reasoning and discovery are separate changes');
for (const entry of manifest.patches) {
  const patch = read(`./${entry.path}`).toString('utf8');
  const additions = patch.split('\n').filter(line => line.startsWith('+') && !line.startsWith('+++')).length;
  assert.ok(additions < 900, 'each review step stays below 900 added lines');
}
const discovery = read(`./${manifest.patches.at(-1).path}`).toString('utf8');
assert.doesNotMatch(discovery, /^diff --git a\/src\/sessions\/agent-session-export\.(?:json|transcript)\.ts /m);
assert.deepEqual(metadata.patchSeries, manifest.patches.map(patch => patch.path));
for (const entry of manifest.patches) {
  const patch = read(`./${entry.path}`);
  assert.equal(sha256(patch), entry.sha256, 'patch integrity');
  assert.ok(patch.toString('utf8').startsWith(`From ${entry.commit} `));
  assert.doesNotMatch(patch.toString('utf8'), /^diff --git a\/(?:docs\/|config\/knip|scripts\/asr-export-fixture)/m);
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
assert.equal(records.length, 9);
assert.equal(result.status, 'completed');
assert.equal(result.durationMs, 7);
assert.equal(result.ts, '2026-10-31T12:00:06Z');
assert.equal(records.filter((record) => record.type === 'tool_result').length, 1);
assert.ok(!Object.hasOwn(result, 'input'));
assert.equal(inference._meta['ai.openclaw'].nativeUsage.input, '9007199254740993');
assert.equal(validation.warnings, 0);
console.log('OpenClaw package integrity and completion, settings and numeric contracts passed.');
