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

test('Goose synthetic export passes schema and stream checks without warnings', () => {
  const result = validateFile(fileURLToPath(file('samples/asr/session.jsonl')));
  assert.equal(result.valid, true);
  assert.deepEqual(result.diagnostics, []);
  assert.ok(stream.endsWith('\n'));
});

test('Goose sample preserves native facts and limits claims to recorded evidence', () => {
  assert.equal(records[0].sessionId, native.id);
  assert.equal(records[0].producer.method, 'native');
  assert.equal(records[0].agent.name, 'goose');
  assert.equal(records[1].id, native.conversation[0].id);
  assert.equal(records[1].content[0].text, native.conversation[0].content[0].text);
  assert.ok(records[1].ts > records[2].ts);
  const call = records.find((row) => row.type === 'tool_call');
  const sourceCall = native.conversation[1].content[1];
  assert.equal(call.callId, sourceCall.id);
  assert.equal(call.name, sourceCall.toolCall.value.name);
  assert.equal(call.input.nativeCounter, '9007199254740993');
  assert.equal(call.truncated, undefined);
  const approval = records.find((row) => row.type === 'approval');
  assert.equal(native.conversation[3].content[0].data.permission, 'allow_once');
  assert.equal(approval.decision, 'approved');
  assert.equal(approval.scope, 'once');
  const results = records.filter((row) => row.type === 'tool_result');
  assert.equal(results.length, 1);
  assert.equal(results[0].content[0].text, native.conversation[4].content[0].toolResult.value.content[0].text);
  assert.equal(records[4].type, 'gap');
  const reasoning = records.flatMap((row) => row.content ?? []).find((part) => part.type === 'reasoning');
  assert.deepEqual(reasoning, { type: 'reasoning', visibility: 'encrypted' });
  assert.equal(records[0].endedAt, undefined);
  assert.equal(records[1].author, undefined);
  assert.ok(!records.some((row) => row.type === 'inference' || row.type === 'vcs' || row.type === 'file_change'));
});

test('Goose patch is parseable and matches its recorded provenance', () => {
  const provenance = JSON.parse(readFileSync(file('manifest.json'), 'utf8')).provenance;
  const patch = readFileSync(file(provenance.patch));
  assert.equal(createHash('sha256').update(patch).digest('hex'), provenance.patchSha256);
  assert.ok(patch.toString().startsWith(`From ${provenance.commit} `));
  const parsed = spawnSync('git', ['apply', '--numstat', '-'], { input: patch, encoding: 'utf8', cwd: fileURLToPath(new URL('../../', import.meta.url)) });
  assert.equal(parsed.status, 0, parsed.stderr);
  assert.match(parsed.stdout, /crates\/goose\/src\/session\/export_agent_session\.rs/);
  assert.match(parsed.stdout, /crates\/goose\/tests\/agent_session_export\.rs/);
  assert.doesNotMatch(parsed.stdout, /goose-self-test\.yaml/);
});
