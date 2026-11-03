import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { repositorySnapshot, reasoningPart } from '../dist/capture.js';

test('live repository facts handle nested directories, detached worktrees and private remotes', t => {
  const dir = mkdtempSync(join(tmpdir(), 'asr-repository-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const git = (...args) => execFileSync('git', ['-C', dir, ...args], { encoding: 'utf8' }).trim();
  git('init', '-q', '-b', 'initial');
  git('-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid', 'commit', '-q', '--allow-empty', '-m', 'Baseline');
  git('remote', 'add', 'origin', 'https://example.invalid/team/repo.git');
  const sub = join(dir, 'sub'); mkdirSync(sub);
  const facts = repositorySnapshot(sub);
  assert.deepEqual(facts, { cwd: sub, repos: [{ path: dir, branch: 'initial', head: git('rev-parse', 'HEAD'), remote: 'https://example.invalid/team/repo.git' }] });
  git('worktree', 'add', '-q', '--detach', join(dir, 'linked'));
  assert.equal(repositorySnapshot(join(dir, 'linked')).repos[0].branch, undefined);
  for (const remote of ['https://synthetic:password@example.invalid/repo', 'https://example.invalid/repo?token=synthetic-private']) {
    git('remote', 'set-url', 'origin', remote);
    assert.equal(repositorySnapshot(sub).repos[0].remote, undefined);
  }
  const path = process.env.PATH;
  try { process.env.PATH = '/no-git'; assert.deepEqual(repositorySnapshot(sub), { cwd: sub }); }
  finally { process.env.PATH = path; }
  assert.deepEqual(repositorySnapshot('relative'), {});
});

test('reasoning labels describe empty, summarized and explicitly full content', () => {
  assert.deepEqual(reasoningPart('', 'full'), { type: 'reasoning', visibility: 'omitted' });
  assert.deepEqual(reasoningPart('summary', 'summary'), { type: 'reasoning', visibility: 'summary', summary: ['summary'] });
  assert.deepEqual(reasoningPart('visible'), { type: 'reasoning', text: 'visible' });
  assert.deepEqual(reasoningPart('opaque', 'encrypted'), { type: 'reasoning', visibility: 'encrypted' });
  assert.equal(reasoningPart('visible', 'full').visibility, 'full');
  assert.deepEqual(reasoningPart(undefined, undefined, ['summary']), { type: 'reasoning', visibility: 'summary', summary: ['summary'] });
});
