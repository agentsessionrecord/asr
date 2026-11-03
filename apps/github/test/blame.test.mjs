import assert from 'node:assert/strict';
import test from 'node:test';
import { createHash } from 'node:crypto';
import { addedByEdit } from '../dist/git.js';
import { setup, validate } from './helpers.mjs';

const change = rows => rows.find(r => r.type === 'file_change');
const vcs = rows => rows.find(r => r.type === 'vcs');

test('status precedence and unique call pairing govern fallback success', async t => {
  const s = setup(t), record = vcs(s.records);
  record.callId = 'commit';
  record.status = 'failed'; s.save('session.jsonl', s.records);
  assert.equal((await s.report()).committedBy.length, 0);
  record.status = 'unknown'; s.save('session.jsonl', s.records);
  assert.equal((await s.report()).committedBy.length, 1);
  s.records.push({ type: 'tool_call', id: 'duplicate-call', callId: 'commit', name: 'other' });
  s.save('session.jsonl', s.records);
  let report = await s.report();
  assert.equal(report.committedBy.length, 0);
  assert.ok(report.sessions[0].approvals.every(a => !a.paired));
  s.records.pop();
  s.records.find(r => r.id === 'commit-result').status = 'failed';
  record.status = 'completed'; s.save('session.jsonl', s.records);
  assert.equal((await s.report()).committedBy.length, 1);
  record.evidence = 'reported'; s.save('session.jsonl', s.records);
  assert.equal((await s.report()).committedBy.length, 0);
  record.evidence = 'observed'; record.action = 'push'; s.save('session.jsonl', s.records);
  assert.equal((await s.report()).committedBy.length, 0);
});

test('prefix IDs require subject, parent checks and local branch reachability', async t => {
  const s = setup(t), record = vcs(s.records);
  delete record.commit; record.commitPrefix = s.head.slice(0, 9);
  record.subject = s.repository.subject(s.head); record.parents = [s.base]; record.parentCount = 1;
  s.save('session.jsonl', s.records); assert.equal((await s.report()).committedBy.length, 1);
  for (const [field, value] of [['subject', 'Wrong'], ['parents', []], ['parentCount', 0]]) {
    const old = record[field]; record[field] = value;
    s.save('session.jsonl', s.records); assert.equal((await s.report()).committedBy.length, 0, field);
    record[field] = old;
  }
  delete record.subject; s.save('session.jsonl', s.records); assert.equal((await s.report()).committedBy.length, 0);
  record.subject = s.repository.subject(s.head); record.action = 'rebase';
  s.save('session.jsonl', s.records); assert.equal((await s.report()).committedBy.length, 0);
  record.action = 'commit';
  s.git('reset', '--hard', s.base);
  // A fresh reader is required because repository caches cover one report snapshot.
  const { Git } = await import('../dist/git.js');
  assert.equal(new Git(s.directory, ['/work/project']).checks(record, s.head), false);
});

test('full IDs also withhold credit when recorded checks fail or repository differs', async t => {
  const s = setup(t), record = vcs(s.records);
  record.subject = 'Wrong'; s.save('session.jsonl', s.records);
  assert.equal((await s.report()).committedBy.length, 0);
  delete record.subject; record.repo = '/other/project'; s.save('session.jsonl', s.records);
  assert.equal((await s.report()).committedBy.length, 0);
  delete record.repo;
  s.records[0].repos.push({ path: '/other/project' }); s.save('session.jsonl', s.records);
  assert.equal((await s.report()).committedBy.length, 0);
  assert.equal(s.repository.resolvePath({ header: { cwd: '/work/project' }, records: s.records }, '../outside.txt'), undefined);
});

test('edit evidence excludes dirty context, after-only states and ambiguous replacements', async t => {
  const s = setup(t), record = change(s.records);
  record.edits = [{ oldText: 'new\nold\n', newText: 'new\ncontext\n' }];
  s.save('session.jsonl', s.records); assert.equal((await s.report()).editedBy.length, 0);
  delete record.edits; record.after = { text: 'context\nnew\n' };
  s.save('session.jsonl', s.records); assert.equal((await s.report()).editedBy.length, 0);
  record.before = { text: 'context\nnew\n' };
  s.save('session.jsonl', s.records); assert.equal((await s.report()).editedBy.length, 0);
  record.before.text = 'context\nold\n';
  s.save('session.jsonl', s.records); assert.equal((await s.report()).editedBy.length, 1);
  assert.deepEqual([...addedByEdit(s.repository, { edits: [{ oldText: 'old\n', newText: 'new\n' }] }, 'new\nnew\n', false)], []);
  assert.deepEqual([...addedByEdit(s.repository, { edits: [{ oldText: 'context\nold\n', newText: 'context\nnew\n' }] }, 'context\nnew\n', false)], [2]);
  assert.deepEqual([...addedByEdit(s.repository, { edits: [{ oldText: 'ol', newText: 'ne' }] }, 'new\n', false)], []);
  assert.deepEqual([...addedByEdit(s.repository, { edits: [{ oldText: 'old\n', newText: 'new\n' }] }, 'gnew\nnew\n', false)], []);
});

test('patches and object states supply edit evidence without executing embedded text', async t => {
  const s = setup(t), record = change(s.records);
  delete record.edits;
  record.patch = '--- a/file.txt\n+++ b/file.txt\n@@ -1,2 +1,2 @@\n context\n-old\n+new\n';
  s.save('session.jsonl', s.records); assert.equal((await s.report()).editedBy.length, 1);
  delete record.patch;
  record.before = { objectId: s.git('rev-parse', `${s.base}:file.txt`) };
  record.after = { objectId: s.git('rev-parse', `${s.head}:file.txt`) };
  s.save('session.jsonl', s.records); assert.equal((await s.report()).editedBy.length, 1);
  record.after = { text: 'context\nnew\n', objectIdType: 'sha256', objectId: createHash('sha256').update('context\nnew\n').digest('hex') };
  s.save('session.jsonl', s.records); assert.equal((await s.report()).editedBy.length, 1);
  record.after.objectId = 'b'.repeat(64);
  s.save('session.jsonl', s.records); assert.equal((await s.report()).editedBy.length, 0);
  const patch = '@@ -1 +1 @@\n-old\n+new\n\\ No newline at end of file\n';
  assert.deepEqual([...addedByEdit(s.repository, { patch }, 'new', false)], [1]);
});

test('latest surviving changes retain alternatives and sessions remain competing', async t => {
  const s = setup(t);
  s.records.push({ ...structuredClone(change(s.records)), id: 'change-later', ts: '2020-01-01T00:00:00Z' });
  s.save('session.jsonl', s.records);
  let report = await s.report();
  assert.equal(report.editedBy[0].record, 'change-later');
  assert.deepEqual(report.editedBy[0].alternatives.map(c => c.record), ['change']);
  const second = structuredClone(s.records); second[0].sessionId = 'other';
  s.save('other.jsonl', second);
  report = await s.report();
  assert.equal(report.editedBy.length, 2); assert.ok(report.editedBy.every(c => c.competing));
  change(s.records).actor = 'human'; delete change(s.records).callId;
  s.records.pop(); s.save('session.jsonl', s.records);
  report = await s.report(); assert.ok(report.editedBy.some(c => c.actor === 'human'));
  change(s.records).actor = 'external'; s.save('session.jsonl', s.records);
  report = await s.report(); assert.equal(report.editedBy.length, 1);
});

test('missing call and inference links stay unresolved and requested models are labeled', async t => {
  const s = setup(t);
  const model = s.records.find(r => r.type === 'inference').model;
  delete model.id; s.save('session.jsonl', s.records);
  let report = await s.report();
  assert.equal(report.editedBy[0].model, 'synthetic-requested'); assert.equal(report.editedBy[0].modelKind, 'requested');
  s.records.find(r => r.type === 'tool_call').turnId = 'unknown-turn';
  s.records.find(r => r.type === 'tool_call').inferenceId = 'absent';
  s.save('session.jsonl', s.records); report = await s.report();
  assert.equal(report.editedBy[0].model, undefined); assert.deepEqual(report.editedBy[0].prompts, []);
  assert.ok(report.unresolved.some(r => r.endsWith('#absent')));
  s.records.push({ type: 'tool_call', id: 'duplicate-edit', callId: 'edit', name: 'other', inferenceId: 'inference' });
  s.save('session.jsonl', s.records); report = await s.report();
  assert.equal(report.editedBy[0].call, undefined); assert.equal(report.editedBy[0].model, undefined);
});

test('recorded moves carry source edits without granting authorship to the move', async t => {
  const s = setup(t);
  s.git('mv', 'file.txt', 'moved.txt'); const head = s.commit('Move the file');
  s.records.push({ type: 'file_change', id: 'move', path: 'moved.txt', oldPath: 'file.txt', op: 'move', status: 'applied', actor: 'human' });
  s.save('session.jsonl', s.records);
  const report = await s.report({ ...s.pr, head, commits: [head] });
  assert.ok(report.editedBy.some(r => r.record === 'change' && r.path === 'moved.txt'));
  assert.ok(report.editedBy.every(r => r.record !== 'move'));
});

test('exact rewrite annotations carry commit history but recheck surviving edited lines', async t => {
  const s = setup(t);
  s.write('file.txt', 'context\nnew\nremoved\n');
  const old = s.commit('Original two lines');
  const record = change(s.records); record.edits[0].newText = 'new\nremoved\n';
  vcs(s.records).commit = old;
  s.git('reset', '--hard', s.base); s.write('file.txt', 'context\nnew\nconflict\n'); const successor = s.commit('Successor');
  s.save('session.jsonl', s.records);
  const annotation = { type: 'annotation', id: 'rewrite', session: 'com.example.agent:run%3A7', kind: 'vcs', at: '2026-01-01T00:00:00Z', source: { name: 'synthetic-sync' },
    data: { action: 'rebase', status: 'completed', evidence: 'observed', repo: '/work/project', rewrites: [{ from: old, to: successor }] } };
  validate(s.save('rewrite.annotations.jsonl', [annotation]));
  const pr = { ...s.pr, head: successor, commits: [successor] };
  const report = await s.report(pr);
  assert.equal(report.committedBy.length, 1); assert.equal(report.committedBy[0].recordedCommit, old);
  // The changed replacement block no longer matches uniquely. No edit credit is guessed.
  assert.equal(report.editedBy.length, 0);
  delete record.edits; record.before = { text: 'context\nold\n' }; record.after = { text: 'context\nnew\nremoved\n' };
  s.save('session.jsonl', s.records);
  const surviving = await s.report(pr);
  assert.deepEqual(surviving.editedBy.map(e => e.line), [2]);
  annotation.data.status = 'failed'; s.save('rewrite.annotations.jsonl', [annotation]);
  assert.equal((await s.report(pr)).committedBy.length, 0);
});

test('squash merges include the landed commit and multi-parent merges use non-first-parent reachability', async t => {
  const s = setup(t);
  let report = await s.report({ ...s.pr, merged: true, mergeCommit: s.head, commits: [s.base] });
  assert.deepEqual(report.commits, [s.head]); assert.equal(report.editedBy.length, 1);
  s.git('checkout', '-b', 'feature-a', s.base); s.write('a.txt', 'a\n'); const a = s.commit('Feature A');
  s.git('checkout', '-b', 'feature-b', s.base); s.write('b.txt', 'b\n'); const b = s.commit('Feature B');
  s.git('checkout', '-b', 'feature-c', s.base); s.write('c.txt', 'c\n'); const c = s.commit('Feature C');
  s.git('checkout', 'main'); s.git('merge', '--no-ff', 'feature-a', 'feature-b', 'feature-c', '-m', 'Octopus merge');
  const merge = s.git('rev-parse', 'HEAD');
  report = await s.report({ ...s.pr, head: merge, merged: true, mergeCommit: merge });
  assert.deepEqual(new Set(report.commits), new Set([a, b, c]));
  assert.ok(!report.commits.includes(merge)); assert.ok(!report.commits.includes(s.head));
});

test('confirmed new files support after-only evidence and literal pathspecs stay literal', async t => {
  const s = setup(t), file = ':(glob)*.txt';
  s.write(file, '++new-file\n'); const head = s.commit('Add a literal filename');
  s.records.push({ type: 'file_change', id: 'new-file', path: '/work/project/' + file, op: 'add', status: 'applied', after: { text: '++new-file\n' }, actor: 'human' });
  s.save('session.jsonl', s.records);
  const report = await s.report({ ...s.pr, head, commits: [head] });
  assert.deepEqual(report.editedBy.map(c => [c.path, c.line, c.actor]), [[file, 1, 'human']]);
});

test('PR action status stays distinct from references and annotation membership grants no credit', async t => {
  const s = setup(t);
  s.records.push({ type: 'vcs', id: 'pr-action', action: 'pr_merge', status: 'unknown', evidence: 'observed', repo: '/work/project', callId: 'commit',
    pr: { repository: 'example/project', number: 7, mergeCommit: s.head } });
  s.save('session.jsonl', s.records);
  let report = await s.report();
  assert.ok(report.sessions[0].reasons.includes('pr_merge:unconfirmed'));
  assert.ok(!report.sessions[0].reasons.includes('pr_merge:completed'));
  s.save('session.jsonl', [s.records[0]]);
  const annotation = { type: 'annotation', id: 'landed', session: 'com.example.agent:annotation-only', kind: 'outcome', at: '2026-01-01T00:00:00Z', source: { name: 'synthetic-sync' },
    data: { status: 'merged', pr: { repository: 'example/project', number: 7, mergeCommit: s.head } } };
  validate(s.save('outcome.annotations.jsonl', [annotation]));
  report = await s.report({ ...s.pr, merged: true });
  assert.deepEqual(report.commits, [s.head]);
  assert.equal(report.committedBy.length, 0); assert.equal(report.editedBy.length, 0);
  assert.ok(report.unresolved.includes('com.example.agent:annotation-only'));
  await assert.rejects(s.report({ ...s.pr, head: 'b'.repeat(40) }), /unavailable/);
});
