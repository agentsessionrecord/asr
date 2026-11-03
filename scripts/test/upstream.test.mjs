import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { cpSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { pathToFileURL } from 'node:url';
import { repositoryRoot } from '../lib/files.mjs';
import { inspectPackage, reproducePackage } from '../lib/upstream-package.mjs';

const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');

function setup(t) {
  const root = mkdtempSync(path.join(tmpdir(), 'asr-upstream-test-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const directory = path.join(root, 'goose');
  cpSync(path.join(repositoryRoot, 'upstream/goose'), directory, { recursive: true });
  const manifest = JSON.parse(readFileSync(path.join(directory, 'manifest.json'), 'utf8'));
  const save = () => writeFileSync(path.join(directory, 'manifest.json'), JSON.stringify(manifest));
  return { root, directory, manifest, save };
}

test('package checks reject changed, missing and unlisted files', t => {
  const { directory, manifest } = setup(t);
  inspectPackage(directory);
  const patch = path.join(directory, manifest.patches[0].path);
  const bytes = readFileSync(patch);
  writeFileSync(patch, Buffer.concat([bytes, Buffer.from('\n')]));
  assert.throws(() => inspectPackage(directory), /patches\//);
  writeFileSync(patch, bytes);
  const sample = path.join(directory, 'samples/asr/session.jsonl');
  const stream = readFileSync(sample);
  rmSync(sample);
  assert.throws(() => inspectPackage(directory), /every package file/);
  writeFileSync(sample, stream);
  writeFileSync(path.join(directory, 'unlisted.txt'), 'synthetic');
  assert.throws(() => inspectPackage(directory), /every package file/);
});

test('native sample privacy is checked even when its digest is updated', t => {
  const { directory, manifest, save } = setup(t);
  const file = 'samples/native/native.json';
  const syntheticToken = 'sk-' + 'a'.repeat(24);
  const bytes = Buffer.from(JSON.stringify({ api_key: syntheticToken }));
  writeFileSync(path.join(directory, file), bytes);
  manifest.files[file] = sha256(bytes);
  save();
  assert.throws(() => inspectPackage(directory), /native\.json/);
});

test('ordered replay preserves a dirty checkout and rejects reversed patches', async t => {
  const { root, directory, manifest, save } = setup(t);
  const checkout = path.join(root, 'source');
  mkdirSync(checkout);
  const git = (...args) => execFileSync('git', args, { cwd: checkout, encoding: 'utf8' }).trim();
  git('init', '-q');
  git('config', 'user.name', 'Synthetic Contributor');
  git('config', 'user.email', 'synthetic@example.invalid');
  git('config', 'commit.gpgsign', 'false');
  const commit = value => {
    writeFileSync(path.join(checkout, 'value.txt'), value + '\n');
    git('add', 'value.txt');
    git('commit', '-qm', value);
    return git('rev-parse', 'HEAD');
  };
  manifest.base = commit('base');
  commit('first');
  manifest.head = commit('second');
  rmSync(path.join(directory, 'patches'), { recursive: true });
  git('format-patch', '--output-directory', path.join(directory, 'patches'), `${manifest.base}..HEAD`);
  manifest.patches = readdirSync(path.join(directory, 'patches')).sort().map(name => {
    const file = `patches/${name}`;
    const bytes = readFileSync(path.join(directory, file));
    return { path: file, commit: bytes.toString().split(' ')[1], sha256: sha256(bytes) };
  });
  manifest.checks = [];
  for (const file of Object.keys(manifest.files)) if (file.startsWith('patches/')) delete manifest.files[file];
  for (const patch of manifest.patches) manifest.files[patch.path] = patch.sha256;
  save();
  writeFileSync(path.join(checkout, 'value.txt'), 'uncommitted synthetic value\n');
  git('add', 'value.txt');
  writeFileSync(path.join(checkout, 'value.txt'), 'unstaged synthetic value\n');
  const before = git('diff', 'HEAD');
  const staged = git('diff', '--cached');
  const url = pathToFileURL(directory + path.sep);
  await reproducePackage(url, checkout);
  assert.equal(git('rev-parse', 'HEAD'), manifest.head);
  assert.equal(git('diff', 'HEAD'), before);
  assert.equal(git('diff', '--cached'), staged);
  const first = readFileSync(path.join(directory, manifest.patches[0].path));
  const second = readFileSync(path.join(directory, manifest.patches[1].path));
  for (const [index, bytes] of [second, first].entries()) {
    const patch = manifest.patches[index];
    writeFileSync(path.join(directory, patch.path), bytes);
    patch.commit = bytes.toString().split(' ')[1];
    patch.sha256 = sha256(bytes);
    manifest.files[patch.path] = patch.sha256;
  }
  manifest.head = manifest.patches.at(-1).commit;
  save();
  await assert.rejects(reproducePackage(url, checkout), /patch failed/);
  assert.equal(git('diff', 'HEAD'), before);
  assert.equal(git('diff', '--cached'), staged);
});
