import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import test from 'node:test';
import { analyzeCommit } from '../src/attribution.ts';
import { makeAuthorship, parseAuthorship, serializeAuthorship, sessionKey, traceKey, authorshipCandidates } from '../src/git-ai.ts';
import { linkRef, parseLinks, sessionUrl, trailers, writeLinks } from '../src/notes.ts';
import { asBytes, header, modelEdit, root, session, setup, validatedSession, vcs } from './helpers.mjs';

test('mixed standard note routes all three key formats and preserves unknown numbers', () => {
  const text = readFileSync(new URL('fixtures/mixed.git-ai.txt', import.meta.url), 'utf8');
  const note = parseAuthorship(text), exported = serializeAuthorship(note);
  assert.equal(note.attestations.length, 3); assert.equal(note.attestations[0].path, 'src/synthetic file.ts');
  assert.match(exported, /900719925474099312345/);
  const entries = authorshipCandidates(note, [session([]), session([], { agent: { name: 'claude-code' }, sessionId: 'legacy-synthetic' })]);
  assert.deepEqual(entries.map(e => e.status), ['candidate', 'human-link', 'candidate']);
  assert.deepEqual(parseAuthorship(exported), note);
  for (const bad of [text.replace('1-2,5', '2-1'), text.replace('1-2,5', '1-2,2'), text.replace('1-2,5', '0'),
    text.replace('authorship/3.0.0', 'authorship/99'), text.replace('"schema_version":', '"schema_version":"duplicate","schema_version":')])
    assert.throws(() => parseAuthorship(bad));
});

test('deterministic Git AI keys use native IDs and encoded ASR citations', () => {
  const nativeId = 'run:7# %';
  assert.equal(sessionKey('codex', nativeId), `s_${createHash('sha256').update(`codex:${nativeId}`).digest('hex').slice(0, 14)}`);
  const ref = 'codex:run%3A7%23%20%25#edit%23%201';
  assert.equal(traceKey(ref), `t_${createHash('sha256').update(ref).digest('hex').slice(0, 14)}`);
});

test('write and read actual local notes, keep history stable and export only edit matches', t => {
  const f = setup(t); f.put('file.txt', 'context\nnew\n'); const id = f.commit();
  const s = validatedSession([...modelEdit(), vcs(id)]), analysis = analyzeCommit(f.git, id, [s], f.maps);
  const exported = makeAuthorship(analysis, [s]); assert.deepEqual(exported.diagnostics, []);
  const text = serializeAuthorship(exported.note);
  assert.match(text, /  s_[a-f0-9]{14}::t_[a-f0-9]{14} 2\n/);
  assert.doesNotMatch(text, /Synthetic task|messages_url|total_additions|requested/);
  assert.equal(f.git.writeNote(id, 'refs/notes/ai', text), true);
  assert.equal(f.git.writeNote(id, 'refs/notes/ai', text), false);
  assert.deepEqual(parseAuthorship(f.git.note(id, 'refs/notes/ai')).attestations, exported.note.attestations);
  assert.equal(f.run('rev-parse', 'HEAD'), id);
  assert.throws(() => f.git.writeNote(id, 'refs/notes/ai', text.replace('synthetic-model', 'other-model')));
  assert.equal(f.git.note(id, 'refs/notes/commits'), undefined);
});

test('namespace collisions, requested-only and conflicting served models withhold Git AI entries', t => {
  const f = setup(t); f.put('file.txt', 'context\nnew\n'); const id = f.commit();
  const s = session(modelEdit()), analysis = analyzeCommit(f.git, id, [s], f.maps);
  const namespaced = session([], { namespace: 'other-installation' });
  const collision = makeAuthorship(analysis, [s, namespaced]);
  assert.equal(collision.note.attestations.length, 0); assert.equal(collision.diagnostics[0].code, 'ambiguous-git-ai-session-key');
  const requested = session(modelEdit().map(r => r.type === 'inference' ? { ...r, model: { requested: 'alias' } } : r));
  const requestedAnalysis = analyzeCommit(f.git, id, [requested], f.maps);
  assert.equal(requestedAnalysis.lines[0].editedBy.model.kind, 'requested');
  assert.equal(makeAuthorship(requestedAnalysis, [requested]).diagnostics[0].code, 'git-ai-needs-served-model');
  const multi = { ...analysis, lines: [...analysis.lines, { ...analysis.lines[0], line: 3,
    editedBy: { ...analysis.lines[0].editedBy, model: { kind: 'served', value: 'other-model' } } }] };
  assert.equal(makeAuthorship(multi, [s]).note.attestations.length, 0);
});

test('session link notes merge idempotently, preserve unknown data and reject foreign notes', t => {
  const f = setup(t), id = f.base;
  assert.equal(writeLinks(f.git, id, [{ session: 'codex:one', url: 'https://example.com/one' }]), true);
  assert.equal(writeLinks(f.git, id, [{ session: 'codex:one', url: 'https://example.com/one' }]), false);
  f.git.writeNote(id, linkRef, '{"schema":"asr-links/1","sessions":[{"session":"codex:one","future":false}],"future":900719925474099312345}', true);
  writeLinks(f.git, id, [{ session: 'codex:two' }]);
  const note = f.git.note(id, linkRef);
  assert.match(note, /900719925474099312345/); assert.equal(parseLinks(note).sessions[0].future, false);
  f.git.writeNote(id, linkRef, 'foreign note', true);
  assert.throws(() => writeLinks(f.git, id, [{ session: 'codex:three' }]));
  assert.equal(f.git.note(id, linkRef).trim(), 'foreign note');
  assert.throws(() => sessionUrl('javascript:alert(1)', 'codex:a'));
  assert.throws(() => sessionUrl('https://synthetic:synthetic@example.com', 'codex:a'));
  assert.throws(() => parseLinks('{"schema":"asr-links/1","sessions":[{"session":"not a reference"}]}'));
});

test('only final Agent-Session trailers are candidate links', () => {
  assert.deepEqual(trailers('Mention Agent-Session: codex:fake\n\nBody\n'), []);
  assert.deepEqual(trailers('Title\n\nAgent-Session: codex:one#edit\nAgent-Session-Url: https://example.com\nAgent-Session: codex:two\n'), ['codex:one', 'codex:two']);
});

test('CLI inspection, export and explicit local note writes need no service', t => {
  const f = setup(t); f.put('file.txt', 'context\nnew\n'); const id = f.commit();
  const store = path.join(f.directory, 'store'); mkdirSync(store);
  writeFileSync(path.join(store, 'synthetic.jsonl'), asBytes([header(), ...modelEdit(), vcs(id)]));
  const config = path.join(f.directory, 'config.json');
  writeFileSync(config, JSON.stringify({ repo: f.repo, store, repositories: f.maps }));
  const run = command => execFileSync(process.execPath, ['--experimental-strip-types', '--disable-warning=ExperimentalWarning',
    path.join(root, 'exporters/git-notes/cli.ts'), command, config, id], { encoding: 'utf8' });
  assert.equal(JSON.parse(run('inspect')).committedBy.length, 1);
  assert.equal(parseAuthorship(run('export-ai')).attestations.length, 1);
  assert.equal(JSON.parse(run('write-links')).changed, true);
  assert.equal(JSON.parse(run('write-links')).changed, false);
  assert.equal(JSON.parse(run('write-ai')).changed, true);
  assert.equal(JSON.parse(run('read-ai')).candidates[0].status, 'candidate');
});

test('committed synthetic ASR fixture passes the validator CLI with zero warnings', () => {
  const output = execFileSync(process.execPath, [path.join(root, 'tools/validator/bin/asr-validate.js'),
    path.join(import.meta.dirname, 'fixtures/synthetic.jsonl')], { encoding: 'utf8' });
  assert.match(output, /0 errors, 0 warnings, 8 complete records/);
});
