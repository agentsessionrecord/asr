import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createServer } from 'node:http';
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { GitLabApi, buildReport, marker, renderSummary } from '../src/index.ts';
import { writeLinks } from '../../../exporters/git-notes/src/notes.ts';
import { makeAuthorship, serializeAuthorship } from '../../../exporters/git-notes/src/git-ai.ts';
import { analyzeCommit } from '../../../exporters/git-notes/src/attribution.ts';
import { loadStore } from '../../../exporters/git-notes/src/reader.ts';
import { asBytes, fileChange, header, modelEdit, root, session, setup, validatedSession, vcs } from '../../../exporters/git-notes/test/helpers.mjs';

const emptyStore = sessions => ({ sessions, annotations: [], diagnostics: [] });
async function mock(t, handler) {
  const errors = [];
  const server = createServer(async (req, res) => {
    try { await handler(req, res); }
    catch (e) { errors.push(e); res.writeHead(500).end('{}'); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(async () => { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); assert.deepEqual(errors, []); });
  return `http://127.0.0.1:${server.address().port}/api/v4`;
}
function respond(res, value, next) {
  res.writeHead(200, { 'Content-Type': 'application/json', ...(next ? { 'x-next-page': next } : {}) }).end(JSON.stringify(value));
}

test('API response allocation is bounded and the oversized stream is cancelled', async () => {
  let cancelled = false;
  const fetcher = async () => new Response(new ReadableStream({
    start(controller) { controller.enqueue(new Uint8Array(16 * 1024 * 1024 + 1)); },
    cancel() { cancelled = true; },
  }));
  const api = new GitLabApi('http://127.0.0.1/api/v4', 'synthetic-token', fetcher);
  await assert.rejects(api.request('/user'), /oversized/);
  assert.equal(cancelled, true);
});

test('merge request report finds edits and candidate links but annotations and notes grant no credit', t => {
  const f = setup(t); f.put('file.txt', 'context\nnew\n'); const id = f.commit('Synthetic task\n\nAgent-Session: codex:missing');
  const editor = validatedSession([...modelEdit(), { type: 'gap', id: 'gap', reason: 'not_recorded', detail: 'Never post synthetic gap text.' },
    { type: 'session_info', id: 'loss', missing: ['approvals'] }], { sessionId: 'editor' });
  const linked = session([], { sessionId: 'linked' });
  writeLinks(f.git, id, [{ session: linked.ref, url: 'https://untrusted.invalid/not-fetched' }]);
  const store = { ...emptyStore([editor, linked]), annotations: [{ type: 'annotation', id: 'outcome', session: linked.ref,
    kind: 'outcome', data: { commit: id, status: 'kept' } }] };
  const report = buildReport(f.git, [id], store, f.maps), body = renderSummary(report, 'https://sessions.example.com/session');
  assert.equal(report.commits[0].committedBy.length, 0);
  assert.equal(report.commits[0].lines[0].editedBy.session, editor.ref);
  assert.equal(report.sessions.find(s => s.session === 'codex:missing').details, undefined);
  assert.deepEqual(report.sessions.find(s => s.session === linked.ref).reasons, ['note-link', 'annotation-link']);
  assert.match(body, /Committed by: unknown/); assert.match(body, /Declared losses: approvals/);
  assert.match(body, /Recorded approvals: 1/); assert.match(body, /Gap codex:editor/);
  assert.doesNotMatch(body, /Synthetic task|Never post synthetic gap text|untrusted\.invalid/);
});

test('Git AI is a candidate lookup and cannot transfer authorship or commit credit', t => {
  const f = setup(t); f.put('file.txt', 'context\nnew\n'); const id = f.commit();
  const original = session(modelEdit()), note = makeAuthorship(analyzeCommit(f.git, id, [original], f.maps), [original]);
  f.git.writeNote(id, 'refs/notes/ai', serializeAuthorship(note.note));
  const withoutEvidence = session([]), report = buildReport(f.git, [id], emptyStore([withoutEvidence]), f.maps);
  assert.deepEqual(report.sessions[0].reasons, ['git-ai-candidate']);
  assert.equal(report.commits[0].committedBy.length, 0);
  assert.ok(report.commits[0].lines.every(l => !l.editedBy));
});

test('summary escapes Markdown, HTML and mentions and never executes stream instructions', t => {
  const f = setup(t); f.put('file.txt', 'context\nnew\n'); const id = f.commit();
  const sentinel = path.join(f.directory, 'must-not-exist');
  const s = session([...modelEdit(), { type: 'tool_call', id: 'untrusted', callId: 'untrusted', name: 'shell', inputText: `touch ${sentinel}` },
    { type: 'message', id: 'resource', role: 'user', content: [{ type: 'resource_link', uri: 'https://untrusted.invalid/resource', name: 'synthetic' }] }],
    { sessionId: '@all`[x]<script>', missing: ['@all **synthetic** <script>'] });
  const body = renderSummary(buildReport(f.git, [id], emptyStore([s]), f.maps));
  assert.doesNotMatch(body, /@all|<script>|touch |untrusted\.invalid/);
  assert.match(body, /&#64;all/); assert.equal(existsSync(sentinel), false);
});

test('mock GitLab API paginates commits and creates, updates and reuses only owned summary notes', async t => {
  const f = setup(t); f.put('file.txt', 'context\nnew\n'); const id = f.commit();
  const mr = JSON.parse(readFileSync(new URL('fixtures/merge-request.json', import.meta.url)));
  let notes = [{ id: 3, author: { id: 11 }, body: `${marker}\nUnrelated user's note.` }], posts = 0, puts = 0;
  const requests = [];
  const base = await mock(t, async (req, res) => {
    assert.equal(req.headers['private-token'], 'synthetic-token'); requests.push(`${req.method} ${req.url}`);
    const url = new URL(req.url, 'http://127.0.0.1'), prefix = '/api/v4/projects/example%2Fproject/merge_requests/7';
    if (url.pathname === prefix) return respond(res, mr);
    if (url.pathname === `${prefix}/commits`) return respond(res, [{ id }], url.searchParams.get('page') === '1' ? '2' : undefined);
    if (url.pathname === '/api/v4/user') return respond(res, { id: 99 });
    if (url.pathname === `${prefix}/notes` && req.method === 'GET') return respond(res, notes);
    const buffers = []; for await (const b of req) buffers.push(b);
    const body = JSON.parse(Buffer.concat(buffers).toString());
    if (url.pathname === `${prefix}/notes` && req.method === 'POST') {
      posts++; const note = { id: 4, author: { id: 99 }, body: body.body }; notes.push(note); return respond(res, note);
    }
    if (url.pathname === `${prefix}/notes/4` && req.method === 'PUT') { puts++; notes[1].body = body.body; return respond(res, notes[1]); }
    assert.fail('Unexpected mock request.');
  });
  const api = new GitLabApi(base, 'synthetic-token');
  assert.deepEqual(await api.commits(f.git, 'example/project', 7), [id]);
  const summary = renderSummary(buildReport(f.git, [id], emptyStore([session([vcs(id)])]), f.maps));
  assert.equal((await api.postSummary('example/project', 7, summary)).action, 'created');
  assert.equal((await api.postSummary('example/project', 7, summary)).action, 'unchanged');
  assert.equal((await api.postSummary('example/project', 7, summary + '\nUpdated.')).action, 'updated');
  assert.equal(posts, 1); assert.equal(puts, 1); assert.equal(notes[0].body, `${marker}\nUnrelated user's note.`);
  assert.ok(requests.some(r => r.endsWith('commits?per_page=100&page=2')));
});

test('landed multi-parent and squash merges use the spec membership rules', async t => {
  const f = setup(t); f.run('checkout', '-b', 'feature'); f.put('feature.txt', 'feature\n'); const feature = f.commit('Feature');
  f.run('checkout', 'main'); f.put('main.txt', 'main\n'); f.commit('Main');
  f.run('merge', '--no-ff', 'feature', '-m', 'Merge'); const merge = f.run('rev-parse', 'HEAD');
  assert.deepEqual(f.git.mergeRequestCommits(merge, [f.base]), [feature]);
  f.run('checkout', '-b', 'squashed', f.base); f.put('feature.txt', 'feature\n'); const squash = f.commit('Squash');
  assert.deepEqual(f.git.mergeRequestCommits(squash, [feature]), [squash]);
  let mergeInfo = { state: 'merged', squash_commit_sha: squash, merge_commit_sha: null };
  const base = await mock(t, (req, res) => {
    if (req.url.includes('/commits')) return respond(res, [{ id: feature }]);
    respond(res, mergeInfo);
  });
  assert.deepEqual(await new GitLabApi(base, 'synthetic-token').commits(f.git, 'example/project', 7), [squash]);
  mergeInfo = { ...mergeInfo, merge_commit_sha: merge };
  assert.deepEqual(await new GitLabApi(base, 'synthetic-token').commits(f.git, 'example/project', 7), [feature]);
});

test('API rejects pagination loops, invalid IDs, insecure remote origins and response leakage', async t => {
  assert.throws(() => new GitLabApi('http://gitlab.example.com/api/v4', 'synthetic-token'));
  assert.throws(() => new GitLabApi('https://synthetic:synthetic@gitlab.example.com/api/v4', 'synthetic-token'));
  const loop = await mock(t, (_req, res) => respond(res, [], '1'));
  await assert.rejects(new GitLabApi(loop, 'synthetic-token').list('/list'), /pagination/);
  const forbidden = await mock(t, (_req, res) => res.writeHead(403).end('Private synthetic diagnostic.'));
  await assert.rejects(new GitLabApi(forbidden, 'synthetic-token').request('/list'), e => e.message === 'GitLab returned HTTP 403.');
  const bad = await mock(t, (req, res) => req.url.includes('/commits') ? respond(res, [{ id: '--untrusted-option' }]) : respond(res, { state: 'opened' }));
  const f = setup(t);
  await assert.rejects(new GitLabApi(bad, 'synthetic-token').commits(f.git, 'example/project', 7), /invalid commit/);
});

test('offline CLI produces a reviewable comment with no API configuration', t => {
  const f = setup(t), store = path.join(f.directory, 'store'); mkdirSync(store);
  writeFileSync(path.join(store, 'session.jsonl'), asBytes([header(), vcs(f.base)]));
  const config = path.join(f.directory, 'config.json'); writeFileSync(config, JSON.stringify({ repo: f.repo, store, repositories: f.maps }));
  const output = execFileSync(process.execPath, ['--experimental-strip-types', '--disable-warning=ExperimentalWarning',
    path.join(root, 'apps/gitlab/cli.ts'), config, '--offline', f.base], { encoding: 'utf8' });
  assert.match(output, /Committed by: codex:synthetic-7/);
  assert.equal(loadStore(store).sessions.length, 1);
});
