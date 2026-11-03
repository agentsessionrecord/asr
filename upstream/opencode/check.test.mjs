import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { validate } from '../../tools/validator/src/index.js';
import { privacyFindings } from '../../scripts/check-privacy.mjs';
import { checkWriting } from '../../scripts/check-writing.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const read = (file) => readFileSync(path.join(root, file), 'utf8');
const sha = (text) => createHash('sha256').update(text).digest('hex');

function added(patch, file) {
  const marker = `diff --git a/${file} b/${file}\n`;
  assert.ok(patch.includes(marker), `Patch contains ${file}`);
  return patch.split(marker)[1].split('\ndiff --git ')[0].split('\n')
    .filter((line) => line.startsWith('+') && !line.startsWith('+++'))
    .map((line) => line.slice(1)).join('\n') + '\n';
}

for (const agent of [process.env.ASR_UPSTREAM_AGENT ?? 'opencode']) {
  const directory = `upstream/${agent}`;
  const manifest = JSON.parse(read(`${directory}/manifest.json`)).provenance;
  const patch = read(`${directory}/${manifest.patch}`);
  const native = JSON.parse(read(`${directory}/samples/native/native.json`));
  const text = read(`${directory}/samples/asr/session.jsonl`);
  const records = text.trimEnd().split('\n').map(JSON.parse);

  test(`${agent}: patch is pinned and contains the tested native fixture`, () => {
    assert.equal(sha(patch), manifest.patchSha256);
    assert.ok(patch.startsWith(`From ${manifest.commit} `));
    assert.ok(patch.includes(`base-commit: ${manifest.base}`));
    assert.deepEqual(JSON.parse(added(patch, manifest.fixture)), native);
    assert.ok(added(patch, manifest.test).includes('test('));
    const output = execFileSync('git', ['apply', '--numstat', '--'], {
      input: patch, cwd: root, encoding: 'utf8',
    });
    assert.ok(output.includes(manifest.module));
  });

  test(`${agent}: synthetic output passes the reference validator`, () => {
    const result = validate(text);
    assert.equal(result.valid, true);
    assert.deepEqual(result.diagnostics, []);
    execFileSync(process.execPath, [
      'tools/validator/bin/asr-validate.js', '--summary', `${directory}/samples/asr/session.jsonl`,
    ], { cwd: root });
    assert.equal(records[0].agent.name, agent);
    assert.equal(records[0].producer.method, 'native');
    assert.equal(records[0].sessionId, 'ses_synthetic');
    assert.equal(records[0].endedAt, undefined);
    assert.ok(records[0].missing.includes('approvals'));
    assert.ok(records[0].missing.includes('copies'));
  });

  test(`${agent}: native completion facts keep their positions and accounting`, () => {
    const call = records.findIndex((record) => record.type === 'tool_call');
    const result = records.findIndex((record) => record.type === 'tool_result');
    const notice = records.findIndex((record) => record.content?.[0]?.text === 'A recorded notice.');
    assert.ok(call < notice && notice < result);
    assert.ok(records[notice].ts < records[call].ts);
    assert.equal(records[result].content[0].text, 'synthetic\n');
    assert.equal(records.filter((record) => record.type === 'tool_result' && record.callId === 'read-1').length, 1);
    const inference = records.find((record) => record.type === 'inference');
    const finish = agent === 'opencode'
      ? native.find((event) => event.type === 'session.step.ended').data
      : native.map((row) => JSON.parse(row.data).part).find((part) => part?.type === 'step-finish');
    assert.equal(inference.usage.inputTokens, finish.tokens.input + finish.tokens.cache.read + finish.tokens.cache.write);
    assert.equal(inference.usage.outputTokens, finish.tokens.output + finish.tokens.reasoning);
    assert.equal(inference.model.requested, 'requested-model');
    assert.equal(inference.model.id, undefined);
    assert.equal(records[call].inferenceId, inference.id);
    assert.ok(records.indexOf(inference) > result);
    if (agent === 'kilo') {
      assert.equal(records[result - 1].type, 'approval');
      assert.equal(records[result - 1].by, 'policy');
      assert.equal(records[result - 1].ts, undefined);
      assert.deepEqual(records[result].input, { path: '/work/demo/rewritten.txt' });
      assert.deepEqual(records.at(-1).agentSettings, { mode: null, approval: null });
    } else {
      assert.equal(records.some((record) => record.type === 'approval'), false);
    }
  });

  test(`${agent}: bundle privacy and proposal writing checks pass`, () => {
    for (const [file, content] of [
      ['patch', patch], ['native', JSON.stringify(native)], ['output', text],
      ['proposal', read(`${directory}/PROPOSAL.md`)],
    ]) assert.deepEqual(privacyFindings(content), [], file);
    assert.deepEqual(checkWriting(read(`${directory}/PROPOSAL.md`), `${directory}/PROPOSAL.md`), []);
  });

  if (agent === 'opencode') test('opencode: actual patched exporter reproduces the sample', async () => {
    const source = added(patch, manifest.module)
      .replace(/^export \* as AgentSession from .*\n/m, '')
      .replace(/^import \{ OPENCODE_VERSION \} from .*$/m,
        `const OPENCODE_VERSION = ${JSON.stringify(records[0].producer.version)}`);
    const js = stripTypeScriptTypes(source);
    const exporter = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
    assert.deepEqual(exporter.records('ses_synthetic', native), records);
    assert.throws(() => exporter.records('ses_missing', []), /creation history/);
  });
}
