#!/usr/bin/env node
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { privacyFindings } from '../../scripts/check-privacy.mjs';

const root = path.resolve(fileURLToPath(new URL('../../', import.meta.url)));
for (const agent of [process.argv[2] ?? 'openhands']) {
  const directory = path.join(root, 'upstream', agent);
  const metadata = JSON.parse(readFileSync(path.join(directory, 'manifest.json'), 'utf8')).provenance;
  const patch = readFileSync(path.join(directory, metadata.patch), 'utf8');
  assert.equal(createHash('sha256').update(patch).digest('hex'), metadata.sha256);
  assert.match(metadata.baseCommit, /^[a-f0-9]{40}$/);
  assert.match(metadata.commit, /^[a-f0-9]{40}$/);
  const syntax = spawnSync('git', ['apply', '--numstat', '-'], { input: patch, encoding: 'utf8', cwd: root });
  assert.equal(syntax.status, 0, `${agent}: malformed patch`);
  assert.ok(syntax.stdout.includes('test'), `${agent}: patch must include upstream tests`);
  for (const filename of [metadata.patch, 'PROPOSAL.md', 'samples/native/native.json', 'samples/asr/session.jsonl']) {
    assert.deepEqual(privacyFindings(readFileSync(path.join(directory, filename), 'utf8')), [], `${agent}/${filename}: privacy findings`);
  }
  const native = JSON.parse(readFileSync(path.join(directory, 'samples/native/native.json'), 'utf8'));
  const records = readFileSync(path.join(directory, 'samples/asr/session.jsonl'), 'utf8').trimEnd().split('\n').map(JSON.parse);
  assert.equal(records[0].sessionId, native.sessionId ?? native.conversation_id);
  assert.equal(records[0].agent.name, agent);
  assert.equal(records[0].producer.method, 'native');
  const prompt = agent === 'openhands' ? native.events[0].llm_message.content[0].text
    : agent === 'deepagents' ? native.messages[0].data.content : native.content[0].content;
  const message = records.find((record) => record.type === 'message' && record.role === 'user');
  assert.equal(message.content[0].text, prompt, `${agent}: native prompt text changed`);
  assert.equal(message.author, undefined, `${agent}: role alone cannot establish human authorship`);
  const call = records.find((record) => record.type === 'tool_call');
  const result = records.find((record) => record.type === 'tool_result');
  assert.equal(call.callId, result.callId);
  const nativeCall = agent === 'openhands' ? native.events[1].tool_call
    : agent === 'deepagents' ? native.messages[1].data.tool_calls[0] : native.content[1].tool_calls[0];
  assert.equal(call.callId, nativeCall.id);
  if (agent === 'astrbot') {
    assert.equal(call.inputText, nativeCall.function.arguments);
    assert.equal(result.status, 'unknown');
  } else if (agent === 'deepagents') {
    assert.deepEqual(call.input, nativeCall.args);
    assert.equal(result.status, 'completed');
  } else {
    assert.deepEqual(call.input, native.events[1].action);
    assert.equal(result.status, 'completed');
  }
  assert.ok(!records.some((record) => record.type === 'inference'));
  assert.ok(records[0].missing.includes('usage'));
  const validation = spawnSync(process.execPath, ['tools/validator/bin/asr-validate.js', '--json', path.join(directory, 'samples/asr/session.jsonl')], { cwd: root, encoding: 'utf8' });
  assert.equal(validation.status, 0, validation.stdout);
  const summary = JSON.parse(validation.stdout);
  assert.equal(summary.errors, 0);
  assert.equal(summary.warnings, 0);
  console.log(`${agent}: patch syntax, integrity, native sample facts, privacy and ${summary.records} ASR records passed`);
}
