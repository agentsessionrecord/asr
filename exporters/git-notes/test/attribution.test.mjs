import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import { analyzeCommit, addedChunks } from '../src/attribution.ts';
import { fileChange, modelEdit, session, setup, validatedSession, vcs } from './helpers.mjs';

test('verified committing and editing remain separate, with causing model and prompt', t => {
  const f = setup(t); f.put('file.txt', 'context\nnew\n'); const id = f.commit();
  const editor = validatedSession(modelEdit(), { sessionId: 'editor' }), committer = validatedSession([vcs(id)], { sessionId: 'committer' });
  const result = analyzeCommit(f.git, id, [editor, committer], f.maps);
  assert.equal(result.committedBy[0].session, 'codex:committer');
  assert.equal(result.lines.length, 1); assert.equal(result.lines[0].line, 2);
  assert.deepEqual(result.lines[0].editedBy, { session: 'codex:editor', record: 'codex:editor#edit', call: 'codex:editor#call',
    prompt: 'codex:editor#prompt', model: { value: 'synthetic-model', kind: 'served' }, alternatives: [] });
});

test('commit prefixes require exact subject, parent metadata, reachability and allowed action', t => {
  const f = setup(t); f.put('file.txt', 'context\nnew\n'); const id = f.commit('Exact subject');
  const prefix = { commit: undefined, commitPrefix: id.slice(0, 9), subject: 'Exact subject' };
  const analyze = extra => analyzeCommit(f.git, id, [session([vcs(id, { ...prefix, ...extra })])], f.maps).committedBy;
  assert.equal(analyze({}).length, 1);
  for (const extra of [{ subject: 'wrong' }, { subject: undefined }, { parentCount: 2 }, { parents: [] },
    { action: 'rebase' }, { action: 'pr_link' }, { status: 'failed' }, { evidence: 'reported' }, { commit: id }]) assert.equal(analyze(extra).length, 0);
  f.run('checkout', '--detach', id); f.run('branch', '-f', 'main', f.base);
  assert.equal(analyze({}).length, 0);
  assert.equal(analyzeCommit(f.git, id, [session([vcs(id)])], f.maps).committedBy.length, 1);
});

test('full commits still check metadata, copies, success and unique fallback results', t => {
  const f = setup(t), id = f.base;
  for (const r of [vcs(id, { subject: 'wrong' }), vcs(id, { parents: [id] }), vcs(id, { parentCount: 1 }),
    vcs(id, { copiedFrom: { record: 'original' } }), vcs(id, { status: 'unknown' }), vcs(id, { action: 'push' })])
    assert.equal(analyzeCommit(f.git, id, [session([r])], f.maps).committedBy.length, 0);
  const call = { type: 'tool_call', id: 'call', callId: 'c', name: 'shell' };
  const result = { type: 'tool_result', id: 'result', callId: 'c', status: 'completed' };
  const records = [call, result, vcs(id, { status: 'unknown', callId: 'c' })];
  assert.equal(analyzeCommit(f.git, id, [validatedSession(records)], f.maps).committedBy.length, 1);
  const duplicate = session([...records, { ...call, id: 'second' }]);
  assert.equal(analyzeCommit(f.git, id, [duplicate], f.maps).committedBy.length, 0);
});

test('before/after and replacements credit additions only, excluding dirty context', t => {
  const f = setup(t, 'old\n'); f.put('file.txt', 'dirty\nnew\n'); const id = f.commit();
  const s = session([fileChange({ edits: undefined, before: { text: 'dirty\nold\n' }, after: { text: 'dirty\nnew\n' } })]);
  const answer = analyzeCommit(f.git, id, [s], f.maps);
  assert.equal(answer.lines.find(l => l.line === 1).editedBy, undefined);
  assert.ok(answer.lines.find(l => l.line === 2).editedBy);
  const afterOnly = session([fileChange({ edits: undefined, after: { text: 'dirty\nnew\n' }, baseCommit: f.base })]);
  assert.ok(analyzeCommit(f.git, id, [afterOnly], f.maps).lines.every(l => !l.editedBy));
  const replacement = session([fileChange({ edits: [{ oldText: 'dirty\nold\n', newText: 'dirty\nnew\n' }] })]);
  assert.ok(!analyzeCommit(f.git, id, [replacement], f.maps).lines[0].editedBy);
});

test('repeated snippets and ambiguous LCS context stay uncredited', t => {
  const f = setup(t); f.put('file.txt', 'new\nnew\n'); const id = f.commit();
  assert.ok(analyzeCommit(f.git, id, [session([fileChange()])], f.maps).lines.every(l => !l.editedBy));
  assert.deepEqual(addedChunks('same\n', 'same\nsame\n'), []);
  assert.deepEqual(addedChunks('context\nold\n', 'context\nnew\n'), [['new\n']]);
  assert.deepEqual(addedChunks('old\n'.repeat(1500), 'new\n'.repeat(1500)), []);
});

test('latest surviving local edit wins with alternatives and competing sessions stay unresolved', t => {
  const f = setup(t); f.put('file.txt', 'context\nnew\n'); const id = f.commit();
  const s = session([fileChange(), fileChange({ id: 'later', ts: '2025-01-01T00:00:00Z' })]);
  const one = analyzeCommit(f.git, id, [s], f.maps).lines[0].editedBy;
  assert.equal(one.record, 'codex:synthetic-7#later'); assert.deepEqual(one.alternatives, ['codex:synthetic-7#edit']);
  const two = analyzeCommit(f.git, id, [s, session([fileChange()], { sessionId: 'other' })], f.maps).lines[0];
  assert.equal(two.editedBy, undefined); assert.equal(two.competing.length, 2);
  assert.equal(analyzeCommit(f.git, id, [session([fileChange({ actor: 'human' })])], f.maps).lines[0].editedBy.actor, 'human');
  const external = analyzeCommit(f.git, id, [session([fileChange({ actor: 'external' })])], f.maps).lines[0];
  assert.equal(external.editedBy, undefined); assert.equal(external.untracked.actor, 'external');
});

test('patch additions, object ID evidence and confirmed additions work without borrowing unchanged lines', t => {
  const f = setup(t); f.put('file.txt', 'context\nnew\n'); f.put('added.txt', 'added\n'); const id = f.commit();
  const patch = f.git.run(['diff', '--no-ext-diff', '--no-textconv', f.base, id, '--', 'file.txt']);
  const patched = session([fileChange({ edits: undefined, patch })]);
  assert.ok(analyzeCommit(f.git, id, [patched], f.maps).lines.find(l => l.path === 'file.txt').editedBy);
  for (const objectIdType of ['git-blob-sha1', 'git-blob-sha256', 'sha256']) {
    const state = text => ({ objectIdType, objectId: createHash(objectIdType === 'git-blob-sha1' ? 'sha1' : 'sha256')
      .update(objectIdType === 'sha256' ? text : `blob ${Buffer.byteLength(text)}\0${text}`).digest('hex') });
    const s = session([fileChange({ edits: undefined, before: state('context\nold\n'), after: state('context\nnew\n') })]);
    assert.ok(analyzeCommit(f.git, id, [s], f.maps).lines.find(l => l.path === 'file.txt').editedBy, objectIdType);
  }
  const added = session([fileChange({ path: 'added.txt', op: 'add', edits: undefined, after: { text: 'added\n' } })]);
  assert.ok(analyzeCommit(f.git, id, [added], f.maps).lines.find(l => l.path === 'added.txt').editedBy);
});

test('paths require an explicit matching repository, copies and moves carry only prior edits', t => {
  const f = setup(t); f.put('file.txt', 'context\nnew\n'); const id = f.commit();
  assert.ok(analyzeCommit(f.git, id, [session([fileChange()])], []).lines.every(l => !l.editedBy));
  assert.ok(analyzeCommit(f.git, id, [session([fileChange({ path: '../file.txt' })])], f.maps).lines.every(l => !l.editedBy));
  assert.equal(analyzeCommit(f.git, id, [session([vcs(id, { repo: '/elsewhere' })])], f.maps).committedBy.length, 0);
  f.run('mv', 'file.txt', 'renamed.txt'); f.put('renamed.txt', 'context\nnewer\n'); const moved = f.commit('Move');
  const records = [fileChange({ edits: [{ oldText: 'new\n', newText: 'newer\n' }] }),
    fileChange({ id: 'move', path: 'renamed.txt', oldPath: 'file.txt', op: 'move', edits: undefined })];
  const result = analyzeCommit(f.git, moved, [session(records)], f.maps);
  assert.equal(result.lines.find(l => l.path === 'renamed.txt' && l.line === 2).editedBy.record, 'codex:synthetic-7#edit');
});

test('recorded rewrites carry commit history but recheck surviving edits and never credit the annotation', t => {
  const f = setup(t); f.put('file.txt', 'context\nnew\n'); const original = f.commit('Original');
  f.run('checkout', '-b', 'successor', f.base); f.put('file.txt', 'context\nnew\nresolution\n'); const successor = f.commit('Rewritten');
  const s = session([fileChange(), vcs(original)]);
  const annotation = { type: 'annotation', id: 'rewrite', session: s.ref, kind: 'vcs', data: {
    action: 'rebase', status: 'completed', evidence: 'reported', rewrites: [{ from: original, to: successor }] } };
  const result = analyzeCommit(f.git, successor, [s], f.maps, [annotation]);
  assert.deepEqual(result.committedBy, [{ session: s.ref, record: `${s.ref}#commit`, commit: original }]);
  assert.ok(result.lines.find(l => l.line === 2).editedBy); assert.equal(result.lines.find(l => l.line === 3).editedBy, undefined);
  const without = analyzeCommit(f.git, successor, [s], f.maps);
  assert.equal(without.committedBy.length, 0);
  assert.equal(analyzeCommit(f.git, successor, [s], f.maps, [{ ...annotation, data: { ...annotation.data, status: 'unknown' } }]).committedBy.length, 0);
  const falsePair = { ...annotation, data: { ...annotation.data, rewrites: [{ from: 'a'.repeat(40), to: successor }] } };
  assert.equal(analyzeCommit(f.git, successor, [s], f.maps, [falsePair]).committedBy.length, 0);
});

test('human commits still permit line matches and applied abandoned work remains eligible', t => {
  const f = setup(t); f.put('file.txt', 'context\nnew\n'); const id = f.commit();
  const s = session([fileChange(), { type: 'message', id: 'abandoned', role: 'assistant', content: [{ type: 'text', text: 'Synthetic branch abandoned.' }] }]);
  const result = analyzeCommit(f.git, id, [s], f.maps);
  assert.equal(result.committedBy.length, 0); assert.ok(result.lines[0].editedBy);
});

test('relative repository roots and mapped Windows paths resolve without guessing a nested repository', t => {
  const f = setup(t); f.put('file.txt', 'context\nnew\n'); const id = f.commit();
  const relative = session([fileChange(), vcs(id)], { repos: [{ path: '.' }] });
  const relativeResult = analyzeCommit(f.git, id, [relative], f.maps);
  assert.equal(relativeResult.committedBy.length, 1); assert.ok(relativeResult.lines[0].editedBy);
  const windows = session([fileChange({ path: 'C:\\recorded\\project\\file.txt' }), vcs(id, { repo: 'C:\\recorded\\project' })],
    { cwd: 'C:\\recorded\\project', repos: [{ path: 'C:\\recorded\\project' }] });
  const windowsResult = analyzeCommit(f.git, id, [windows], [{ source: 'C:/recorded/project', local: f.repo }]);
  assert.equal(windowsResult.committedBy.length, 1); assert.ok(windowsResult.lines[0].editedBy);
  const nested = session([fileChange({ path: 'nested/file.txt' })], { repos: [{ path: '/recorded/project' }, { path: '/recorded/project/nested' }] });
  assert.ok(analyzeCommit(f.git, id, [nested], f.maps).lines.every(l => !l.editedBy));
});
