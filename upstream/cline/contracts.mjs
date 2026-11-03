import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { validate } from '../../tools/validator/src/index.js';

// Execute only the new exporter file explicitly named by this patch package.
export function addedFile(patch, filename) {
  const section = patch.split('\ndiff --git ').find(part => part.startsWith(`a/${filename} b/${filename}\n`));
  assert.ok(section, `Missing exporter: ${filename}`);
  assert.match(section, /\nnew file mode 100644\n/);
  assert.match(section, /\n--- \/dev\/null\n/);
  return section.split('\n').filter(line => line.startsWith('+') && !line.startsWith('+++')).map(line => line.slice(1)).join('\n') + '\n';
}

export function registerPatchTests(testUrl) {
  const directory = path.dirname(fileURLToPath(testUrl));
  const load = async () => {
    const manifest = JSON.parse(await readFile(path.join(directory, 'manifest.json'), 'utf8')).provenance;
    const patch = await readFile(path.join(directory, manifest.patch), 'utf8');
    const native = JSON.parse(await readFile(path.join(directory, manifest.fixture), 'utf8'));
    const expected = await readFile(path.join(directory, manifest.sample), 'utf8');
    const source = addedFile(patch, manifest.exporter);
    assert.equal(createHash('sha256').update(source).digest('hex'), manifest.exporterSha256);
    assert.ok(patch.startsWith(`From ${manifest.patchCommit} `));
    const code = stripTypeScriptTypes(source);
    const module = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
    const emit = value => manifest.agent === 'continue' ? module.exportAgentSession(value) : module.exportAgentSession('synthetic-session', value);
    return { manifest, patch, native, expected, emit };
  };
  const valid = output => {
    const result = validate(Buffer.from(output));
    assert.equal(result.valid, true, JSON.stringify(result.diagnostics));
    assert.deepEqual(result.diagnostics, [], JSON.stringify(result.diagnostics));
    return output.trimEnd().split('\n').map(line => JSON.parse(line));
  };
  test(`${path.basename(directory)}: patch provenance and exact sample replay`, async () => {
    const { manifest, patch, native, expected, emit } = await load();
    assert.match(manifest.upstreamCommit, /^[a-f0-9]{40}$/);
    assert.ok(patch.includes(`base-commit: ${manifest.upstreamCommit}`));
    assert.equal(manifest.synthetic, true);
    assert.equal(emit(native), expected);
    const rows = valid(expected);
    assert.equal(rows[0].producer.method, 'native');
    assert.equal(rows[0].agent.name, manifest.agent);
    assert.ok(rows[0].missing.includes('approvals'));
    assert.equal(rows.some(row => row.type === 'inference'), false);
    assert.equal(rows.find(row => row.type === 'tool_result').status, 'completed');
  });
  test(`${path.basename(directory)}: folded results keep their completion position`, async () => {
    const { native, manifest, emit } = await load();
    if (manifest.agent === 'continue') {
      native.history.push({ message: { role: 'user', content: 'Intervening native notice' }, contextItems: [] });
      native.history.push(structuredClone(native.history[2]));
      native.history.at(-1).message.content = 'Final native result';
    } else {
      native.push({ role: 'user', ts: 9000, content: 'Intervening native notice' });
      const result = structuredClone(native[2]);
      result.ts = 1000;
      result.content[0].content = 'Final native result';
      native.push(result);
    }
    const rows = valid(emit(native));
    assert.equal(rows.filter(row => row.type === 'tool_result').length, 1);
    const resultIndex = rows.findIndex(row => row.type === 'tool_result');
    const noticeIndex = rows.findIndex(row => row.content?.[0]?.text === 'Intervening native notice');
    assert.ok(resultIndex > noticeIndex);
    assert.equal(rows[resultIndex].content[0].text, 'Final native result');
    assert.ok(rows[0].missing.includes('tool_result_updates'));
  });
  test(`${path.basename(directory)}: native reasoning keeps summaries, unknown text and omitted blocks`, async () => {
    const { native, manifest, emit } = await load();
    if (manifest.agent === 'continue') {
      native.history = [{ message: { role: 'thinking', content: '' }, contextItems: [] }];
      const rows = valid(emit(native));
      assert.deepEqual(rows.find(row => row.type === 'message').content, [{ type: 'reasoning', visibility: 'omitted' }]);
      native.history[0].message.content = [];
      assert.deepEqual(valid(emit(native)).find(row => row.type === 'message').content, [{ type: 'reasoning', visibility: 'omitted' }]);
      native.history[0].message.content = 'Exact\r\n';
      assert.deepEqual(valid(emit(native)).find(row => row.type === 'message').content,
        [{ type: 'reasoning', text: 'Exact\r\n' }]);
      return;
    }
    native.splice(0, native.length, { id: 'reasoning', role: 'assistant', content: [
      { type: 'thinking', thinking: 'Exact\r\n' },
      { type: 'thinking', thinking: '' },
      { type: 'thinking', signature: 'synthetic-opaque' },
      { type: 'reasoning', text: 'Unknown representation' },
      { type: 'redacted_thinking' },
    ] });
    const rows = valid(emit(native));
    assert.deepEqual(rows.find(row => row.type === 'message').content, [
      { type: 'reasoning', visibility: 'summary', summary: ['Exact\r\n'] },
      { type: 'reasoning', visibility: 'omitted' },
      { type: 'reasoning', visibility: 'omitted' },
      { type: 'reasoning', text: 'Unknown representation' },
      { type: 'reasoning', visibility: 'encrypted' },
    ]);
    if (manifest.agent === 'roo-code') {
      native.splice(0, native.length, { id: 'empty', role: 'assistant', type: 'reasoning', summary: [] });
      assert.deepEqual(valid(emit(native)).find(row => row.type === 'message').content,
        [{ type: 'reasoning', visibility: 'omitted' }]);
    }
  });
  test(`${path.basename(directory)}: credential losses are explicit`, async () => {
    const { native, manifest, emit } = await load();
    if (manifest.agent === 'continue') native.history[1].message.toolCalls[0].function.arguments = '{"password":"synthetic-value"}';
    else native[1].content[1].input.password = { value: 'synthetic-value' };
    const output = emit(native);
    assert.equal(output.includes('synthetic-value'), false);
    const rows = valid(output);
    assert.ok(rows[0].missing.includes('secrets'));
    assert.equal(rows.find(row => row.type === 'tool_call').truncated, true);
  });
}
