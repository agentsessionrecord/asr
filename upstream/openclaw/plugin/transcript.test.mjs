import assert from 'node:assert/strict';
import { test } from 'node:test';
import { exportTranscript } from './transcript.mjs';

test('public projection preserves text and tool evidence with explicit limits', () => {
  const source = [
    { type: 'message', id: 'u', message: { role: 'user', content: 'Exact\r\n' } },
    { type: 'message', id: 'a', message: { role: 'assistant', content: [{ type: 'toolCall', id: 'call-1', name: 'read', arguments: { path: '/work/fixture', credentials: 'excluded-synthetic-value' } }] } },
    { type: 'message', id: 'r', message: { role: 'toolResult', toolCallId: 'call-1', isError: false, content: [{ type: 'text', text: 'done\n' }] } },
  ];
  const text = exportTranscript('synthetic-plugin', source);
  const records = text.trimEnd().split('\n').map(JSON.parse);
  assert.equal(records[2].content[0].text, 'Exact\r\n');
  assert.equal(records[2].author, undefined);
  assert.equal(records.at(-1).status, 'completed');
  assert.equal(records.at(-1).callId, records.at(-2).callId);
  assert.ok(!text.includes('excluded-synthetic-value'));
  assert.ok(!records.some(record => record.type === 'inference'));
  assert.throws(() => exportTranscript('synthetic', [...source, source.at(-1)]), /repeated/);
});


test('refuses unsafe parsed numbers and marks filtered tool output', () => {
  assert.throws(() => exportTranscript('synthetic', [{ value: 9007199254740992 }]), /Unsafe numeric/);
  const records = exportTranscript('synthetic', [{ type: 'message', id: 'result', message: { role: 'toolResult', toolCallId: 'call-1', content: [{ type: 'text', text: 'ghp_' + 'a'.repeat(24) }] } }]).trimEnd().split('\n').map(JSON.parse);
  assert.equal(records.at(-1).truncated, true);
  assert.equal(records.at(-1).content[0].text, '[redacted]');
});
