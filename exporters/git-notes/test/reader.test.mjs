import assert from 'node:assert/strict';
import { readFileSync, readdirSync, writeFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { readSession, readAnnotations, loadStore, reference, citation, sessionSummary, successful } from '../src/reader.ts';
import { validate } from '../../../tools/validator/src/index.js';
import { asBytes, header, session, setup, vcs, root } from './helpers.mjs';

test('reader keeps order and raw numeric lexemes and unions known losses', () => {
  const input = asBytes([header({ missing: ['usage'] }),
    { type: 'session_info', id: 'later', missing: ['approvals'], ts: '2026-01-02T00:00:00Z' },
    { type: 'com.example/future', id: 'earlier', ts: '2026-01-01T00:00:00Z', native: 'SENTINEL' },
    { type: 'session_info', id: 'empty', missing: [] }]).toString().replace('"SENTINEL"', '900719925474099312345');
  const s = readSession(Buffer.from(input));
  assert.deepEqual(s.records.map(r => r.id), ['later', 'earlier', 'empty']);
  assert.match(s.raw[2], /900719925474099312345/);
  assert.deepEqual(s.missing, ['usage', 'approvals']);
});

test('reader recovers malformed complete lines and defers incomplete tails without credit', () => {
  const bytes = Buffer.concat([asBytes([header()]), Buffer.from('{broken}\n'),
    asBytes([vcs('a'.repeat(40))]), Buffer.from('{"type":"gap"')]);
  const s = readSession(bytes);
  assert.equal(s.records.length, 1); assert.equal(s.original.size, 0);
  assert.deepEqual(s.diagnostics.map(d => d.code), ['invalid-json', 'incomplete-line']);
  const duplicate = readSession(Buffer.concat([asBytes([header()]), Buffer.from('{"type":"gap","id":"a","id":"b"}\n')]));
  assert.equal(duplicate.records.length, 0); assert.equal(duplicate.diagnostics[0].code, 'duplicate-key');
  const utf8 = readSession(Buffer.concat([asBytes([header()]), Buffer.from([255, 10]), asBytes([{ type: 'gap', id: 'good', reason: 'unknown' }])]));
  assert.equal(utf8.records[0].id, 'good'); assert.equal(utf8.diagnostics[0].code, 'invalid-utf8');
});

test('copied prefix and individual copies never gain original credit', () => {
  const s = session([vcs('a'.repeat(40)), vcs('b'.repeat(40), { id: 'copy', copiedFrom: { record: 'unknown' } }), vcs('c'.repeat(40), { id: 'own' })],
    { parent: { session: 'codex:missing', kind: 'fork', copiedThrough: 'commit' } });
  assert.deepEqual([...s.original].map(r => r.id), ['own']);
  assert.deepEqual(sessionSummary(s, new Set()).unresolved, ['codex:missing']);
  const unresolved = session([vcs('a'.repeat(40))], { parent: { session: 'codex:missing', kind: 'fork', copiedThrough: 'absent' } });
  assert.equal(unresolved.original.size, 0);
});

test('call and approval pairing rejects duplicates and preserves explicit failed status', () => {
  const records = [
    { type: 'tool_call', id: 'c1', callId: 'reused', name: 'shell' },
    { type: 'tool_call', id: 'c2', callId: 'reused', name: 'shell' },
    { type: 'tool_result', id: 'r', callId: 'reused', status: 'completed' },
    { type: 'approval', id: 'a', callId: 'reused', decision: 'denied' },
  ];
  const s = session(records);
  assert.equal(successful(s, { status: 'unknown', callId: 'reused' }), false);
  assert.equal(sessionSummary(s, new Set()).approvals[0].pairing, 'unpaired');
  assert.equal(successful(session([records[0], records[2]]), { status: 'unknown', callId: 'reused' }), true);
  assert.equal(successful(session([records[0], records[2]]), { status: 'failed', callId: 'reused' }), false);
});

test('session and trace references encode reserved bytes with uppercase escapes', () => {
  const s = session([], { sessionId: 'run:7# %', namespace: 'north:1' });
  assert.equal(reference(s.header), 'codex:north%3A1:run%3A7%23%20%25');
  assert.equal(citation(s, { id: 'edit# 1%' }), 'codex:north%3A1:run%3A7%23%20%25#edit%23%201%25');
});

test('annotation supersedes is applied before using additive vcs facts', () => {
  const annotation = { type: 'annotation', id: 'a', session: 'codex:synthetic-7', kind: 'vcs', at: '2026-01-02T00:00:00Z', source: { name: 'synthetic' },
    data: { action: 'reset', status: 'completed', evidence: 'observed' } };
  const parsed = readAnnotations(asBytes([annotation, { ...annotation, id: 'b', at: '2026-01-01T00:00:00Z', supersedes: 'a' },
    { ...annotation, id: 'c' }]));
  assert.deepEqual(parsed.records.map(r => r.id), ['b', 'c']);
  const titles = readAnnotations(asBytes([
    { ...annotation, id: 't1', kind: 'title', data: { title: 'synthetic-one' } },
    { ...annotation, id: 't2', kind: 'title', at: '2026-01-01T00:00:00Z', supersedes: 't1', data: { title: 'synthetic-corrected' } },
    { ...annotation, id: 't3', session: 'codex:synthetic-7#edit', kind: 'title', data: { title: 'synthetic-record-title' } },
  ]));
  assert.deepEqual(titles.records.map(r => r.id), ['t2', 't3']);
});

test('malformed known records are diagnosed, skipped and cannot grant credit', () => {
  const s = session([{ type: 'vcs', id: 'bad', action: 'commit', status: 'completed', evidence: 'observed', commit: 'not-an-id' },
    { type: 'file_change', id: 'bad-shape', path: null, op: 'modify', status: 'applied' }, vcs('a'.repeat(40))]);
  assert.deepEqual(s.records.map(r => r.id), ['commit']);
  assert.deepEqual(s.diagnostics.map(d => d.code), ['invalid-record-shape', 'invalid-record-shape']);
  assert.equal(s.original.size, 0);
});

test('duplicate store identities withhold credit and symlink-free loading reports bad files', t => {
  const f = setup(t), directory = path.join(f.directory, 'store'); mkdirSync(directory);
  writeFileSync(path.join(directory, 'one.jsonl'), asBytes([header(), vcs(f.base)]));
  writeFileSync(path.join(directory, 'two.jsonl'), asBytes([header(), vcs(f.base)]));
  writeFileSync(path.join(directory, 'invalid.jsonl'), '{}\n');
  const title = { type: 'annotation', id: 'title', session: 'codex:synthetic-7', kind: 'title', at: '2026-01-01T00:00:00Z',
    source: { name: 'synthetic' }, data: { title: 'Synthetic title' } };
  writeFileSync(path.join(directory, 'one.annotations.jsonl'), asBytes([title]));
  writeFileSync(path.join(directory, 'two.annotations.jsonl'), asBytes([{ ...title, at: '2026-01-02T00:00:00Z' }]));
  const store = loadStore(directory);
  assert.equal(store.sessions.length, 2); assert.ok(store.sessions.every(s => s.original.size === 0));
  assert.deepEqual(store.diagnostics.map(d => d.code), ['unreadable-session']);
  assert.equal(store.annotations.length, 1); assert.equal(store.annotations[0].at, '2026-01-02T00:00:00Z');
});

test('all repository sample ASR and example streams are read without network or command execution', () => {
  const files = [];
  function walk(dir) { for (const e of readdirSync(dir, { withFileTypes: true })) {
    const file = path.join(dir, e.name);
    if (e.isDirectory()) walk(file);
    else if (e.name.endsWith('.jsonl') && e.name !== 'native.jsonl' && !e.name.endsWith('.annotations.jsonl') && !file.includes('/native/')) files.push(file);
  } }
  walk(path.join(root, 'samples')); walk(path.join(root, 'examples'));
  assert.ok(files.length >= 15);
  for (const agent of ['claude-code', 'codex']) {
    assert.ok(files.includes(path.join(root, 'samples', agent, 'synthetic-success', 'asr.jsonl')));
  }
  for (const file of files) {
    const bytes = readFileSync(file), result = validate(bytes);
    assert.equal(result.valid, true, path.relative(root, file));
    const s = readSession(bytes), summary = sessionSummary(s, new Set());
    assert.ok(s.ref); assert.equal(s.diagnostics.length, 0);
    assert.ok(Array.isArray(summary.approvals));
    assert.deepEqual(s.raw.join('\n') + '\n', bytes.toString());
  }
});
