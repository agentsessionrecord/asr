import assert from 'node:assert/strict';
import test from 'node:test';
import { adapt } from '../../plugins/remaining-core/adapters.mjs';

test('Cline results require source evidence for their outcome', () => {
  const payload = { taskId: 'synthetic', hookName: 'tool_result', tool_result: { id: 'one', output: 'success' } };
  assert.equal(adapt('cline', payload).result.status, 'unknown');
  for (const error of ['failed', '']) assert.equal(adapt('cline', { ...payload, tool_result: { ...payload.tool_result, error } }).result.status, 'failed');
  assert.equal(adapt('cline', { ...payload, tool_result: { ...payload.tool_result, error: null } }).result.status, 'unknown');
});
