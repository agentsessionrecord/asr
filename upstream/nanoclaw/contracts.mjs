import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { checkWriting } from '../../scripts/check-writing.mjs';
import { privacyFindings } from '../../scripts/check-privacy.mjs';
const read = name => readFileSync(new URL(name, import.meta.url), 'utf8');
for (const name of ['README.md', 'PROPOSAL.md']) {
  assert.deepEqual(checkWriting(read(name), name), []);
  assert.deepEqual(privacyFindings(read(name)), []);
}
const source = read('samples/asr/session.jsonl');
const rows = source.trimEnd().split('\n').map(JSON.parse);
assert.equal(rows[0].producer.method, 'native');
assert.equal(rows[0].agent.name, 'nanoclaw');
assert.equal(new Set(rows.map(row => row.id)).size, rows.length);
assert.ok(!source.includes('endedAt'));
const calls = rows.filter(row => row.type === 'tool_call');
const results = rows.filter(row => row.type === 'tool_result');
const inference = rows.find(row => row.type === 'inference');
if (calls.length && results.length) assert.equal(calls[0].callId, results[0].callId);
assert.equal(calls.length, 1);
assert.equal(results.length, 1);
assert.equal(inference.usage.inputTokens, 15);
assert.equal(inference.usage.outputTokens, 4);
assert.equal(rows.filter(row => row.type === 'inference').length, 1);
assert.equal(calls[0].inferenceId, inference.id);
assert.equal(rows[2].id, '9007199254740993/0');
assert.ok(rows[2].ts > inference.ts);
console.log('nanoclaw: native sample and public writing contracts passed.');
