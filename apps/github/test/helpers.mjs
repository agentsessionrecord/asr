import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Git } from '../dist/git.js';
import { loadStore } from '../dist/store.js';
import { buildReport } from '../dist/report.js';

export const root = fileURLToPath(new URL('../../../', import.meta.url));
export const fixture = () => readFileSync(new URL('./fixtures/session.jsonl', import.meta.url), 'utf8').trim().split('\n').map(JSON.parse);
export function setup(t) {
  const scratch = mkdtempSync(path.join(tmpdir(), 'asr-github-'));
  t.after(() => rmSync(scratch, { recursive: true, force: true }));
  const directory = path.join(scratch, 'repo'), storeDir = path.join(scratch, 'store');
  mkdirSync(directory); mkdirSync(storeDir);
  const env = { ...process.env, GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null',
    GIT_AUTHOR_NAME: 'Synthetic User', GIT_AUTHOR_EMAIL: 'synthetic@example.test', GIT_COMMITTER_NAME: 'Synthetic User',
    GIT_COMMITTER_EMAIL: 'synthetic@example.test', GIT_AUTHOR_DATE: '2026-01-01T00:00:00Z', GIT_COMMITTER_DATE: '2026-01-01T00:00:00Z' };
  const git = (...args) => execFileSync('git', ['-c', 'core.hooksPath=/dev/null', '-C', directory, ...args], { encoding: 'utf8', env, stdio: ['pipe', 'pipe', 'pipe'] }).trim();
  git('init', '-b', 'main');
  const write = (file, text) => { mkdirSync(path.dirname(path.join(directory, file)), { recursive: true }); writeFileSync(path.join(directory, file), text); };
  const commit = (subject) => { git('add', '.'); git('commit', '-m', subject); return git('rev-parse', 'HEAD'); };
  write('file.txt', 'context\nold\n');
  const base = commit('Baseline');
  write('file.txt', 'context\nnew\n');
  const head = commit('Synthetic change\n\nAgent-Session: com.example.agent:run%3A7#commit\nAgent-Session: com.example.agent:unavailable\nAgent-Session-Url: http://127.0.0.1:1/do-not-fetch');
  const records = fixture(); records.find(r => r.type === 'vcs').commit = head;
  const save = (name, rows) => { const file = path.join(storeDir, name); writeFileSync(file, rows.map(r => JSON.stringify(r)).join('\n') + '\n'); return file; };
  const sessionFile = save('session.jsonl', records);
  const repository = new Git(directory, ['/work/project']);
  const pr = { repository: 'example/project', number: 7, head, commits: [head] };
  const report = async (data = pr) => buildReport(repository, await loadStore(storeDir), data);
  return { scratch, directory, storeDir, git, write, commit, base, head, records, save, sessionFile, repository, pr, report };
}
export function validate(file) {
  const result = JSON.parse(execFileSync(process.execPath, [path.join(root, 'tools/validator/bin/asr-validate.js'), '--json', file], { encoding: 'utf8' }));
  assert.equal(result.errors, 0);
  return result;
}
