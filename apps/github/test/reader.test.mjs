import assert from 'node:assert/strict';
import test from 'node:test';
import { readdirSync, readFileSync, symlinkSync } from 'node:fs';
import path from 'node:path';
import { readJSONL, parseRecord, makeSession, loadStore, original, splitRef, sessionRef, ExactNumber } from '../dist/store.js';
import { renderSummary, sessionURL } from '../dist/report.js';
import { root, setup, fixture, validate } from './helpers.mjs';

test('JSONL recovery, exact numbers, duplicate keys, UTF-8 and incomplete tails', () => {
  const parsed = parseRecord('{"type":"future","id":"n","native":{"id":9007199254740993,"decimal":0.1234567890123456789}}');
  assert.ok(parsed.native.id instanceof ExactNumber);
  assert.equal(parsed.native.id.raw, '9007199254740993');
  assert.equal(parsed.native.decimal.raw, '0.1234567890123456789');
  assert.throws(() => parseRecord('{"type":"future","id":"n","nested":{"a":1,"\\u0061":2}}'));
  const data = readJSONL(Buffer.from('{"type":"future","id":"one"}\nnot JSON\n{"type":"future","id":"two"}\n{"type":"future","id":"tail"}'));
  assert.deepEqual(data.records.map(r => r.id), ['one', 'two']);
  assert.deepEqual(data.issues, ['malformed-line:2', 'incomplete-tail:4']);
  assert.match(readJSONL(Buffer.from([255, 10])).issues[0], /malformed/);
  assert.ok(splitRef('com.example.agent:run%3A7#record%20id'));
  assert.equal(splitRef('com.example.agent:run%3a7'), undefined);
  assert.equal(splitRef('com.example.agent:run#'), undefined);
  assert.equal(sessionRef({ agent: { name: 'com.example.agent' }, namespace: 'install:1', sessionId: 'x#% y' }), 'com.example.agent:install%3A1:x%23%25%20y');
});

test('local Git verifies separate commit and surviving edit evidence', async t => {
  const s = setup(t), report = await s.report();
  assert.equal(report.committedBy.length, 1);
  assert.equal(report.committedBy[0].record, 'commit');
  assert.equal(report.editedBy.length, 1);
  assert.equal(report.editedBy[0].line, 2);
  assert.equal(report.editedBy[0].record, 'change');
  assert.equal(report.editedBy[0].model, 'synthetic-served');
  assert.equal(report.editedBy[0].modelKind, 'served');
  assert.deepEqual(report.editedBy[0].prompts, ['prompt']);
  assert.deepEqual(report.sessions[0].missing, ['reasoning', 'approvals']);
  assert.deepEqual(report.sessions[0].approvals.map(a => [a.decision, a.by, a.paired]), [['approved', 'user', true], ['approved', 'policy', true]]);
  assert.deepEqual(report.sessions[0].gaps.map(g => g.reason), ['not_retained']);
  assert.ok(report.unresolved.includes('com.example.agent:unavailable'));
  const summary = renderSummary(report, 'https://sessions.example.test/asr/');
  assert.match(summary, /Committed by/); assert.match(summary, /Edited by/); assert.match(summary, /reasoning, approvals/);
  assert.match(summary, /record=change/); assert.doesNotMatch(summary, /do-not-fetch|Replace the old/);
  assert.equal(validate(s.sessionFile).warnings, 0);
  assert.equal(validate(path.join(root, 'apps/github/test/fixtures/session.jsonl')).warnings, 0);
});

test('copies receive no credit, with prefix boundary in file order', async t => {
  const s = setup(t);
  s.records[0].parent = { session: 'com.example.agent:missing-parent', kind: 'fork', copiedThrough: 'loss-update' };
  s.save('session.jsonl', s.records);
  let report = await s.report();
  assert.equal(report.committedBy.length, 0); assert.equal(report.editedBy.length, 0);
  assert.ok(report.sessions[0].approvals.every(a => a.copied));
  assert.ok(report.unresolved.includes('com.example.agent:missing-parent'));
  delete s.records[0].parent;
  s.records.filter(r => ['vcs', 'file_change'].includes(r.type)).forEach(r => r.copiedFrom = { record: 'unknown-original' });
  s.save('session.jsonl', s.records);
  report = await s.report();
  assert.equal(report.committedBy.length, 0); assert.equal(report.editedBy.length, 0);
  const broken = makeSession([fixture()[0], { type: 'file_change', id: 'edit' }]);
  broken.header.parent = { copiedThrough: 'absent' };
  const reindexed = makeSession(broken.records);
  assert.ok(reindexed.issues.includes('unresolved-copied-boundary'));
  assert.equal(original(reindexed, reindexed.records[1]), false);
  validate(s.sessionFile);
});

test('annotation corrections precede timestamp selection and VCS remains additive', async t => {
  const s = setup(t);
  const annotation = (id, at, kind, data, supersedes) => ({ type: 'annotation', id, session: 'com.example.agent:run%3A7', source: { name: 'synthetic-sync' }, kind, at, data, ...(supersedes ? { supersedes } : {}) });
  const rows = [annotation('out1', '2026-01-02T00:00:00Z', 'outcome', { status: 'merged', commit: s.base }),
    annotation('out2', '2026-01-01T00:00:00Z', 'outcome', { status: 'kept', commit: s.head }, 'out1'),
    annotation('vcs1', '2026-01-01T00:00:00Z', 'vcs', { action: 'pr_link', evidence: 'reported', status: 'completed', pr: { repository: 'example/project', number: 7, commits: [s.head] } }),
    annotation('vcs2', '2026-01-02T00:00:00Z', 'vcs', { action: 'pr_link', evidence: 'reported', status: 'completed', pr: { repository: 'example/project', number: 7, headCommit: s.head } })];
  validate(s.save('facts.annotations.jsonl', rows));
  const store = await loadStore(s.storeDir);
  assert.deepEqual(store.annotations.map(a => a.record.id), ['out2', 'vcs1', 'vcs2']);
  const report = await s.report();
  assert.ok(report.sessions[0].reasons.includes('annotation'));
  assert.equal(report.committedBy.length, 1);
  s.records.splice(s.records.findIndex(r => r.type === 'vcs'), 1);
  s.save('session.jsonl', s.records);
  assert.equal((await s.report()).committedBy.length, 0);
});

test('duplicate session identities and symbolic links cannot choose a store source', async t => {
  const s = setup(t);
  symlinkSync(s.directory, path.join(s.storeDir, 'ignored-link'));
  s.save('same.jsonl', s.records);
  const store = await loadStore(s.storeDir);
  assert.equal(store.sessions.size, 0);
  assert.ok(store.issues.includes('ambiguous-session'));
});

test('all samples and examples are readable without fetching any reference', async () => {
  let sessions = 0, records = 0, annotations = 0;
  function walk(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const file = path.join(directory, entry.name);
      if (entry.isDirectory()) walk(file);
      else if (entry.name.endsWith('.jsonl') && !entry.name.includes('native')) {
        const parsed = readJSONL(readFileSync(file));
        if (parsed.records[0]?.type === 'annotation') { annotations += parsed.records.length; continue; }
        const session = makeSession(parsed.records, parsed.issues);
        if (session) { sessions++; records += session.records.length; assert.equal(session.header.formatVersion, '0.1'); }
      }
    }
  }
  for (const directory of ['examples', 'samples']) walk(path.join(root, directory));
  assert.ok(sessions >= 15); assert.ok(records >= 100); assert.ok(annotations >= 10);
});

test('untrusted text is escaped and content, URLs and private payloads stay out of summaries', async t => {
  const s = setup(t);
  const call = s.records.find(r => r.type === 'tool_call');
  call.inputText = '$(touch /tmp/never-run)'; delete call.input;
  s.records.find(r => r.type === 'gap').detail = '<script>do not display</script>';
  s.records.find(r => r.type === 'inference').model.id = '@everyone [link](javascript:alert(1)) <img src=x>';
  s.records.find(r => r.type === 'message').content[0].text = 'PRIVATE SYNTHETIC TRANSCRIPT';
  s.save('session.jsonl', s.records);
  const summary = renderSummary(await s.report(), 'https://sessions.example.test/asr/');
  assert.doesNotMatch(summary, /@everyone|\[link\]|<img|<script|PRIVATE|never-run/);
  assert.match(summary, /&#64;everyone/);
  assert.throws(() => sessionURL('javascript:alert(1)', 'com.example.agent:run'));
  assert.throws(() => sessionURL('https://user:pass@example.test/', 'com.example.agent:run'));
  assert.doesNotMatch(sessionURL('https://sessions.example.test/', "com.example.agent:run')"), /[()']/);
  assert.match(renderSummary(await s.report(), 'https://sessions.example.test/', 1200), /Summary shortened/);
});

test('parent-side and child-side subagent links combine without transferring credit', async t => {
  const s = setup(t);
  s.records.push({ type: 'tool_call', id: 'spawn', callId: 'spawn', name: 'start_agent', subagent: { session: 'com.example.agent:child' } },
    { type: 'tool_result', id: 'spawn-result', callId: 'spawn', status: 'completed', subagent: { session: 'com.example.agent:child' } });
  s.save('session.jsonl', s.records);
  const child = [{ ...structuredClone(s.records[0]), sessionId: 'child', parent: { session: 'com.example.agent:run%3A7', kind: 'subagent', callId: 'spawn' } }];
  validate(s.save('child.jsonl', child));
  const report = await s.report();
  assert.equal(report.relationships.length, 1);
  assert.equal(report.relationships[0].sources.length, 3);
  assert.deepEqual(report.relationships[0].calls, ['spawn']);
  assert.ok(report.committedBy.every(c => c.session !== 'com.example.agent:child'));
  assert.ok(report.editedBy.every(c => c.session !== 'com.example.agent:child'));
  assert.equal(makeSession([fixture()[0]], ['malformed-line:1']), undefined);
});
