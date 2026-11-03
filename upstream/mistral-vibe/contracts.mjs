import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { privacyFindings } from '../../scripts/check-privacy.mjs';

const read = (name) => readFileSync(new URL(name, import.meta.url), 'utf8');
const native = JSON.parse(read('samples/native/native.json'));
const rows = read('samples/asr/session.jsonl').trimEnd().split('\n').map(JSON.parse);
const expected = JSON.parse(read('TESTS.json'));

assert.equal(native.format, 'vibe.public-session-state/v1');
assert.equal(rows.length, expected.sampleRecords);
assert.equal(rows[0].sessionId, native.session.id);
assert.equal(rows[0].producer.source, native.format);
assert.equal(rows[0].producer.method, 'native');
assert.ok(rows[0].missing.includes('timestamps'));
assert.ok(rows[0].missing.includes('tool_calls'));
assert.ok(native.historyBeforeCursor);
assert.equal(rows[1].type, 'gap');
assert.equal(rows[1].id, 'history-prefix');
assert.equal(new Set(rows.map((row) => row.id)).size, rows.length);

for (const entry of native.history) {
  const row = rows.find((record) => record.id === entry.id);
  assert.ok(row, entry.id);
  assert.equal(row.type, 'message');
  if (entry.type === 'reasoning') {
    assert.deepEqual(row.content, [{ type: 'reasoning', text: entry.text }]);
    assert.equal(row.author, 'model');
  } else {
    assert.equal(row.role, entry.role);
    assert.deepEqual(row.content, entry.content);
    if (entry.role === 'user') assert.equal(row.author, undefined);
  }
  assert.equal(row.ts, undefined);
}
for (const name of ['PROPOSAL.md', 'samples/native/native.json', 'samples/asr/session.jsonl']) {
  assert.deepEqual(privacyFindings(read(name)), [], name);
}
console.log(`mistral-vibe: ${rows.length} synthetic records preserve public snapshot facts`);
