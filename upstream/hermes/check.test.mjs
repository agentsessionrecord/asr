import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { validateFile } from '../../tools/validator/src/index.js';

const file = (name) => new URL(name, import.meta.url);
const native = JSON.parse(readFileSync(file('samples/native/native.json'), 'utf8'));
const stream = readFileSync(file('samples/asr/session.jsonl'), 'utf8');
const records = stream.trimEnd().split('\n').map(JSON.parse);

test('Hermes synthetic export passes schema and stream checks without warnings', () => {
  const result = validateFile(fileURLToPath(file('samples/asr/session.jsonl')));
  assert.equal(result.valid, true);
  assert.deepEqual(result.diagnostics, []);
  assert.ok(stream.endsWith('\n'));
});

test('Hermes sample preserves storage order and model-facing output without inferred outcomes', () => {
  assert.equal(records[0].sessionId, native.session.id);
  assert.equal(records[0].producer.method, 'native');
  assert.equal(records[0].agent.name, 'hermes');
  assert.equal(records[1].id, String(native.messages[0].id));
  assert.equal(records[1].content[0].text, native.messages[0].content);
  assert.ok(records[1].ts > records[2].ts);
  const call = records.find((row) => row.type === 'tool_call');
  const sourceCall = native.messages[1].tool_calls[0];
  assert.equal(call.callId, sourceCall.id);
  assert.equal(call.name, sourceCall.function.name);
  assert.equal(call.input.nativeCounter, '9007199254740993');
  assert.equal(call.truncated, undefined);
  assert.equal(records[4].type, 'gap');
  const results = records.filter((row) => row.type === 'tool_result');
  assert.equal(results.length, 1);
  assert.equal(results[0].status, 'unknown');
  assert.equal(results[0].content[0].text, native.messages[4].api_content);
  const reasoning = records.flatMap((row) => row.content ?? []).find((part) => part.type === 'reasoning');
  assert.equal(reasoning.text, native.messages[5].reasoning_content);
  assert.equal(records[0].endedAt, undefined);
  assert.equal(records[1].author, undefined);
  assert.ok(!records.some((row) => ['inference', 'approval', 'vcs', 'file_change'].includes(row.type)));
});

test('Hermes patch is parseable and matches its recorded provenance', () => {
  const provenance = JSON.parse(readFileSync(file('manifest.json'), 'utf8')).provenance;
  const patch = readFileSync(file(provenance.patch));
  assert.equal(createHash('sha256').update(patch).digest('hex'), provenance.patchSha256);
  assert.ok(patch.toString().startsWith(`From ${provenance.commit} `));
  const parsed = spawnSync('git', ['apply', '--numstat', '-'], { input: patch, encoding: 'utf8', cwd: fileURLToPath(new URL('../../', import.meta.url)) });
  assert.equal(parsed.status, 0, parsed.stderr);
  assert.match(parsed.stdout, /hermes_cli\/session_export_asr\.py/);
  assert.match(parsed.stdout, /tests\/hermes_cli\/test_session_export_asr\.py/);
});
