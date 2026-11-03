import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { Git } from '../src/git.ts';
import { readSession } from '../src/reader.ts';
import { validate } from '../../../tools/validator/src/index.js';

export const root = path.resolve(import.meta.dirname, '../../..');
export const maps = [{ source: '/recorded/project', local: '' }];
export function setup(t, text = 'context\nold\n') {
  const directory = mkdtempSync(path.join(tmpdir(), 'asr-git-notes-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const repo = path.join(directory, 'repo'); mkdirSync(repo);
  const run = (...args) => execFileSync('git', ['-c', 'core.hooksPath=/dev/null', '-C', repo, ...args], {
    encoding: 'utf8', env: { ...process.env, GIT_CONFIG_GLOBAL: '/dev/null', GIT_CONFIG_NOSYSTEM: '1' }, stdio: ['pipe', 'pipe', 'pipe'],
  }).trim();
  run('init', '-b', 'main'); run('config', 'user.name', 'Synthetic Developer'); run('config', 'user.email', 'dev@example.com');
  const put = (name, value) => { mkdirSync(path.dirname(path.join(repo, name)), { recursive: true }); writeFileSync(path.join(repo, name), value); };
  const commit = (message = 'Synthetic change') => { run('add', '--all'); run('commit', '-m', message); return run('rev-parse', 'HEAD'); };
  put('file.txt', text); const base = commit('Synthetic baseline');
  return { directory, repo, run, put, commit, base, git: new Git(repo), maps: [{ source: '/recorded/project', local: repo }] };
}
export const header = (extra = {}) => ({ type: 'session', id: 'header', formatVersion: '0.1', agent: { name: 'codex' }, sessionId: 'synthetic-7',
  producer: { name: 'synthetic-fixture', version: '1', method: 'native' }, cwd: '/recorded/project', repos: [{ path: '/recorded/project' }], ...extra });
export const fileChange = (extra = {}) => ({ type: 'file_change', id: 'edit', path: 'file.txt', op: 'modify', status: 'applied',
  actor: 'harness', edits: [{ oldText: 'old\n', newText: 'new\n' }], ...extra });
export const vcs = (commit, extra = {}) => ({ type: 'vcs', id: 'commit', action: 'commit', status: 'completed', evidence: 'observed', commit, ...extra });
export const asBytes = records => Buffer.from(records.map(r => JSON.stringify(r)).join('\n') + '\n');
export function session(records, extra = {}) { return readSession(asBytes([header(extra), ...records])); }
export function validatedSession(records, extra = {}) {
  const bytes = asBytes([header(extra), ...records]), result = validate(bytes);
  assert.equal(result.valid, true, JSON.stringify(result.diagnostics));
  assert.deepEqual(result.diagnostics, []);
  return readSession(bytes);
}
export function modelEdit(extra = {}) {
  return [
    { type: 'message', id: 'prompt', turnId: 'turn', role: 'user', author: 'human', origin: 'prompt', content: [{ type: 'text', text: 'Synthetic task.' }] },
    { type: 'inference', id: 'inference', turnId: 'turn', model: { id: 'synthetic-model', requested: 'alias' } },
    { type: 'tool_call', id: 'call', callId: 'edit-call', inferenceId: 'inference', turnId: 'turn', name: 'replace', requestedBy: 'model' },
    fileChange({ actor: undefined, callId: 'edit-call', ...extra }),
    { type: 'approval', id: 'approval', callId: 'edit-call', decision: 'approved', by: 'user', scope: 'once' },
    { type: 'tool_result', id: 'result', callId: 'edit-call', status: 'completed' },
  ];
}
