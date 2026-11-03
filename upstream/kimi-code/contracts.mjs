#!/usr/bin/env node
/** Check the seven native export patch packages without building upstream agents. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { validate } from '../../tools/validator/src/index.js';
import { privacyFindings } from '../../scripts/check-privacy.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const agents = [process.argv[2] ?? 'kimi-code'];
const registry = JSON.parse(readFileSync(path.join(root, 'registry.json'), 'utf8'));
let total = 0;
for (const agent of agents) {
  const directory = path.join(root, 'upstream', agent);
  const read = (name) => readFileSync(path.join(directory, name));
  const metadata = JSON.parse(read('manifest.json')).provenance;
  assert.match(metadata.repository, /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+(?:\.git)?$/);
  assert.match(metadata.base, /^[a-f0-9]{40}$/);
  assert.match(metadata.head, /^[a-f0-9]{40}$/);
  assert.notEqual(metadata.base, metadata.head);
  assert.match(metadata.branch, /^codex\/[a-z0-9-]+$/);
  const native = agent === 'deepseek-harness' || agent === 'crush' || agent === 'mistral-vibe' ? 'samples/native/native.json' : 'samples/native/native.jsonl';
  const required = ['patches/0001-native-agent-session-export.patch', native, 'samples/asr/session.jsonl', 'PROPOSAL.md', 'TESTS.json'];
  for (const name of required) assert.ok(metadata.files[name], `${agent}: missing packaged hash for ${name}`);
  for (const [name, digest] of Object.entries(metadata.files)) {
    assert.equal(createHash('sha256').update(read(name)).digest('hex'), digest, `${agent}: ${name} digest`);
  }
  const patch = read('patches/0001-native-agent-session-export.patch').toString('utf8');
  assert.ok(patch.startsWith(`From ${metadata.head} `), `${agent}: patch commit differs`);
  assert.ok(execFileSync('git', ['apply', '--numstat', '-'], { input: patch, cwd: root }).length > 0);
  const text = read('samples/asr/session.jsonl').toString('utf8');
  const result = validate(text, { filename: 'samples/asr/session.jsonl' });
  assert.equal(result.valid, true, `${agent}: ${JSON.stringify(result.diagnostics)}`);
  const tests = JSON.parse(read('TESTS.json'));
  assert.deepEqual(result.diagnostics.map((item) => item.code), tests.sampleWarnings);
  const rows = result.records.map((item) => item.value);
  assert.equal(rows.length, tests.sampleRecords);
  assert.equal(rows[0].agent.name, agent);
  assert.equal(rows[0].producer.method, 'native');
  assert.ok(rows[0].missing.length > 0);
  assert.equal(new Set(rows.map((row) => row.id)).size, rows.length);
  const results = rows.filter((row) => row.type === 'tool_result' && row.callId);
  assert.equal(new Set(results.map((row) => row.callId)).size, results.length);
  assert.ok(!text.includes('SYNTHETIC-OPAQUE'));
  assert.ok(!rows.some((row) => row.endedAt));
  if (agent !== 'grok-build') {
    const nativeText = read(native).toString('utf8');
    if (agent !== 'mistral-vibe') assert.ok(nativeText.includes('SYNTHETIC-OPAQUE'));
    assert.ok(rows.some((row) => row.content?.some((part) => part.text === 'Exact\r\n')));
    assert.ok(rows.some((row) => row.content?.some((part) => part.type === 'reasoning' && part.text === 'Check the fixture.')));
    assert.ok(rows.filter((row) => row.type === 'message' && row.role === 'user').every((row) => row.author === undefined));
  }
  if (agent !== 'pi') assert.ok(!rows.some((row) => row.type === 'inference'));
  else {
    const inference = rows.find((row) => row.type === 'inference');
    assert.equal(inference.model.requested, 'requested');
    assert.equal(inference.model.id, 'served');
    assert.equal(inference.usage.inputTokens, 15);
    assert.equal(inference.cost.amount, 0);
    assert.equal(rows.at(-1).content[0].text, 'Alternative branch.');
  }
  if (agent === 'grok-build') {
    assert.ok(rows.some((row) => row.type === 'approval' && row.decision === 'denied' && !row.by && !row.callId));
    assert.equal(results.length, 1);
    assert.equal(results[0].status, 'denied');
    assert.ok(!rows.some((row) => row.type === 'tool_call'));
  }
  if (agent === 'kimi-code') {
    assert.ok(rows.some((row) => row.type === 'approval' && row.scope === 'session' && !row.by));
  }
  if (agent === 'mux') {
    assert.ok(rows.some((row) => row.type === 'gap' && row.id === 'segment-prefix'));
    assert.equal(results[0].status, 'unknown');
    assert.equal(rows.filter((row) => row.type === 'tool_call').length, 1);
  }
  if (agent === 'mistral-vibe') assert.ok(rows.some((row) => row.type === 'gap' && row.id === 'history-prefix'));
  const entry = registry.entries.find((item) => item.id === `${agent}-native-export-patch`);
  assert.equal(entry.kind, 'patch');
  assert.equal(entry.revision, metadata.head);
  assert.equal(entry.liveTestStatus, tests.liveTestStatus);
  if (tests.liveTestStatus === 'passed') {
    assert.ok(metadata.files['live-test.json']);
    const live = JSON.parse(read('live-test.json'));
    assert.equal(live.validation.exit, 0);
    assert.equal(live.validation.errors, 0);
    assert.deepEqual(live.validation.codes, []);
  }
  // Scan patches and native inputs too, since they are outside the shared fixture paths.
  for (const name of readdirSync(directory, { recursive: true }).filter(name => /\.(md|json|jsonl|patch|native)$/.test(name))) {
    if (name === 'check.mjs') continue;
    assert.deepEqual(privacyFindings(read(name).toString('utf8')), [], `${agent}: privacy finding in ${name}`);
  }
  total += rows.length;
  console.log(`${agent}: ${rows.length} records, zero errors, ${result.diagnostics.length} expected warnings`);
}
console.log(`7 patch packages checked, ${total} sample records.`);
