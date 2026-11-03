import assert from 'node:assert/strict';
import test from 'node:test';
import { createServer } from 'node:http';
import { createHmac, generateKeyPairSync, createVerify } from 'node:crypto';
import { once } from 'node:events';
import { writeFileSync, readFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import path from 'node:path';
import { App, webhookServer, readConfig } from '../dist/app.js';
import { GitHub, installationTokens, appJWT, validSignature } from '../dist/github.js';
import { setup, root } from './helpers.mjs';

const syntheticSecret = 'synthetic-webhook-secret';
const sign = bytes => 'sha256=' + createHmac('sha256', syntheticSecret).update(bytes).digest('hex');
async function listen(t, server) {
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => new Promise(resolve => { server.close(resolve); server.closeAllConnections(); }));
  return `http://127.0.0.1:${server.address().port}`;
}
async function mock(t, setupData) {
  const requests = [], checks = [], comments = [];
  let readHead = setupData.head;
  let commitPages = [[{ sha: setupData.head }]];
  const server = createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const text = Buffer.concat(chunks).toString('utf8'), url = new URL(req.url, 'http://localhost');
    const body = text ? JSON.parse(text) : undefined;
    requests.push({ method: req.method, url: req.url, body, auth: req.headers.authorization });
    const reply = value => res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(value));
    if (req.url === '/app/installations/17/access_tokens') return reply({ token: 'synthetic-installation', expires_at: '2099-01-01T00:00:00Z' });
    if (url.pathname === '/repos/example/project/pulls/7') return reply({ head: { sha: readHead }, merged: false, merge_commit_sha: null });
    if (url.pathname === '/repos/example/project/pulls/7/commits') return reply(commitPages[Number(url.searchParams.get('page')) - 1] ?? []);
    if (/\/commits\/[^/]+\/check-runs$/.test(url.pathname)) return reply({ check_runs: checks });
    if (req.method === 'POST' && url.pathname === '/repos/example/project/check-runs') { const check = { ...body, id: checks.length + 1, app: { id: 123 } }; checks.push(check); return reply(check); }
    if (req.method === 'PATCH' && /\/check-runs\/\d+$/.test(url.pathname)) return reply({ id: Number(url.pathname.split('/').at(-1)), ...body });
    if (req.method === 'GET' && url.pathname === '/repos/example/project/issues/7/comments') return reply(comments);
    if (req.method === 'POST' && url.pathname === '/repos/example/project/issues/7/comments') {
      const comment = { id: comments.length + 1, body: body.body, user: { type: 'Bot' }, performed_via_github_app: { id: 123 } };
      comments.push(comment); return reply(comment);
    }
    if (req.method === 'PATCH' && /\/issues\/comments\/\d+$/.test(url.pathname)) return reply({ id: Number(url.pathname.split('/').at(-1)), ...body });
    res.writeHead(404).end('{}');
  });
  const base = await listen(t, server);
  const config = { store: setupData.storeDir, apiUrl: base, sessionsBaseUrl: 'https://sessions.example.test/asr/', mode: 'check',
    repositories: [{ name: 'example/project', installation: 17, path: setupData.directory, recordedRoots: ['/work/project'] }] };
  const github = new GitHub(base, async () => 'synthetic-installation', 123);
  return { requests, checks, comments, base, config, github, setHead: value => { readHead = value; }, setCommitPages: value => { commitPages = value; } };
}
function event(action = 'synchronize', installation = 17) {
  return Buffer.from(JSON.stringify({ action, number: 7, repository: { full_name: 'example/project' }, installation: { id: installation } }));
}

test('signed HTTP webhooks create and update neutral check runs with retry deduplication', async t => {
  const s = setup(t), m = await mock(t, s), app = new App(m.config, m.github);
  m.checks.push({ id: 900, external_id: 'asr:example/project:7', app: { id: 999 } });
  const base = await listen(t, webhookServer(app, syntheticSecret));
  const raw = event();
  const send = (id, signature = sign(raw)) => fetch(base + '/webhook', { method: 'POST', body: raw,
    headers: { 'x-hub-signature-256': signature, 'x-github-event': 'pull_request', 'x-github-delivery': id } });
  assert.equal((await send('invalid', 'sha256=' + '0'.repeat(64))).status, 401);
  assert.equal(m.requests.length, 0);
  const responses = await Promise.all([send('one'), send('one')]);
  assert.ok(responses.every(r => r.status === 200));
  assert.equal(m.requests.filter(r => r.method === 'POST').length, 1);
  await send('two');
  const posts = m.requests.filter(r => ['POST', 'PATCH'].includes(r.method));
  assert.deepEqual(posts.map(r => r.method), ['POST', 'PATCH']);
  assert.equal(posts[1].url, '/repos/example/project/check-runs/2');
  assert.ok(!Object.hasOwn(posts[1].body, 'head_sha'));
  assert.equal(posts[0].body.conclusion, 'neutral'); assert.equal(posts[0].body.head_sha, s.head);
  assert.match(posts[0].body.output.summary, /Declared losses: reasoning, approvals/);
  assert.match(posts[0].body.output.summary, /record=approval-user/);
  assert.ok(m.requests.every(r => r.auth?.split(' ')[0] === 'Bearer' && r.auth?.split(' ')[1] === 'synthetic-installation'));
  assert.ok(!m.requests.some(r => r.url.includes('do-not-fetch')));
  const wrongInstall = event('opened', 99);
  assert.equal(await app.webhook(wrongInstall, 'pull_request', sign(wrongInstall), syntheticSecret, 'ignored'), 'ignored');
  const ignored = event('edited');
  assert.equal(await app.webhook(ignored, 'pull_request', sign(ignored), syntheticSecret, 'edited'), 'ignored');
});

test('summary comments update only the configured app bot comment', async t => {
  const s = setup(t), m = await mock(t, s);
  m.config.mode = 'comment';
  m.comments.push({ id: 901, body: '<!-- asr-github-summary --> human', user: { type: 'User' } },
    { id: 902, body: '<!-- asr-github-summary --> another bot', user: { type: 'Bot' }, performed_via_github_app: { id: 999 } });
  const app = new App(m.config, m.github), raw = event('opened');
  await app.webhook(raw, 'pull_request', sign(raw), syntheticSecret, 'comment-one');
  await app.webhook(raw, 'pull_request', sign(raw), syntheticSecret, 'comment-two');
  const writes = m.requests.filter(r => ['POST', 'PATCH'].includes(r.method));
  assert.deepEqual(writes.map(r => r.url), ['/repos/example/project/issues/7/comments', '/repos/example/project/issues/comments/3']);
  assert.ok(writes.every(r => r.body.body.startsWith('<!-- asr-github-summary -->')));
});

test('App JWT signing and installation token exchange are local and cached', async t => {
  const s = setup(t), m = await mock(t, s);
  const keys = generateKeyPairSync('rsa', { modulusLength: 2048 });
  const privateKey = keys.privateKey.export({ type: 'pkcs8', format: 'pem' });
  const jwt = appJWT('123', privateKey, 1_700_000_000_000), [head, payload, signature] = jwt.split('.');
  assert.equal(JSON.parse(Buffer.from(head, 'base64url')).alg, 'RS256');
  const data = JSON.parse(Buffer.from(payload, 'base64url'));
  assert.equal(data.iss, '123'); assert.ok(data.exp - data.iat <= 600);
  assert.ok(createVerify('RSA-SHA256').update(head + '.' + payload).verify(keys.publicKey, signature, 'base64url'));
  const tokens = installationTokens(m.base, '123', privateKey);
  assert.equal(await tokens(17), 'synthetic-installation'); assert.equal(await tokens(17), 'synthetic-installation');
  assert.equal(m.requests.length, 1); assert.match(m.requests[0].auth, /^Bearer /);
  assert.equal(validSignature(Buffer.from('changed'), sign(Buffer.from('original')), syntheticSecret), false);
});

test('API commit pagination, truncation and stale-head publication fail safely', async t => {
  const s = setup(t), m = await mock(t, s);
  m.setCommitPages([Array.from({ length: 100 }, () => ({ sha: s.head })), [{ sha: s.base }]]);
  assert.equal((await m.github.pullRequest(17, 'example/project', 7)).commits.length, 101);
  assert.ok(m.requests.some(r => r.url.includes('page=2')));
  m.setCommitPages([Array.from({ length: 100 }, () => ({ sha: s.head })), Array.from({ length: 100 }, () => ({ sha: s.head })), Array.from({ length: 50 }, () => ({ sha: s.head }))]);
  await assert.rejects(m.github.pullRequest(17, 'example/project', 7), /Incomplete/);
  m.setHead(s.base);
  await assert.rejects(m.github.publish(17, s.pr, 'safe summary', 'check'), /changed/);
  assert.equal(m.requests.filter(r => r.method === 'POST').length, 0);
});

test('report CLI writes reviewable files and makes no summary publication calls', async t => {
  const s = setup(t), m = await mock(t, s);
  const keys = generateKeyPairSync('rsa', { modulusLength: 2048 });
  const keyFile = path.join(s.scratch, 'synthetic.pem'), configFile = path.join(s.scratch, 'config.json'), output = path.join(s.scratch, 'report.json');
  writeFileSync(keyFile, keys.privateKey.export({ type: 'pkcs8', format: 'pem' }), { mode: 0o600 });
  writeFileSync(configFile, JSON.stringify(m.config));
  const parsed = await readConfig(configFile);
  assert.equal(parsed.repositories[0].path, s.directory);
  const child = spawn(process.execPath, [path.join(root, 'apps/github/dist/cli.js'), 'report', configFile, 'example/project', '7', output], {
    env: { ...process.env, ASR_GITHUB_APP_ID: '123', ASR_GITHUB_PRIVATE_KEY_FILE: keyFile }, stdio: ['ignore', 'pipe', 'pipe'],
  });
  let error = ''; child.stderr.on('data', bytes => { error += bytes; });
  const [code] = await once(child, 'exit'); assert.equal(code, 0, error);
  const report = JSON.parse(readFileSync(output, 'utf8'));
  assert.equal(report.committedBy.length, 1); assert.equal(report.editedBy.length, 1);
  assert.match(readFileSync(output + '.md', 'utf8'), /approvals/);
  assert.deepEqual(m.requests.filter(r => r.method === 'POST').map(r => r.url), ['/app/installations/17/access_tokens']);
});
