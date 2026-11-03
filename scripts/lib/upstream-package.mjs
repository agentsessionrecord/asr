import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { privacyFindings } from '../check-privacy.mjs';
import { validateFile } from '../../tools/validator/src/index.js';

function execute(command, cwd, env = process.env) {
  const result = spawnSync(command[0], command.slice(1), { cwd, env, encoding: 'utf8' });
  assert.ifError(result.error);
  assert.equal(result.status, 0, result.stdout + result.stderr);
  return result.stdout;
}

export function inspectPackage(directory) {
  const manifest = JSON.parse(readFileSync(path.join(directory, 'manifest.json'), 'utf8'));
  assert.equal(manifest.schemaVersion, 1);
  assert.equal(manifest.agent, path.basename(directory));
  assert.match(manifest.base, /^[a-f0-9]{40}$/);
  assert.match(manifest.head, /^[a-f0-9]{40}$/);
  for (const required of ['PROPOSAL.md', 'check.mjs', 'reproduce.mjs']) readFileSync(path.join(directory, required));
  const safe = (name) => {
    assert.ok(typeof name === 'string' && name.length && !name.includes('\\')
      && !path.isAbsolute(name) && !name.split('/').some(part => part === '..' || part === '.' || !part), name);
    return path.join(directory, name);
  };
  const files = (folder, prefix = '') => readdirSync(folder, { withFileTypes: true }).flatMap(entry => {
    const name = prefix + entry.name;
    assert.ok(entry.isFile() || entry.isDirectory(), `regular package file required: ${name}`);
    return entry.isDirectory() ? files(path.join(folder, entry.name), `${name}/`) : [name];
  });
  assert.deepEqual(files(directory).filter(name => name !== 'manifest.json').sort(), Object.keys(manifest.files).sort(),
    'manifest must cover every package file');
  assert.ok(manifest.patches.length);
  assert.deepEqual(readdirSync(path.join(directory, 'patches')).sort(), manifest.patches.map(patch => path.basename(patch.path)).sort());
  for (const [index, patch] of manifest.patches.entries()) {
    assert.match(patch.path, new RegExp(`^patches/${String(index + 1).padStart(4, '0')}-.+\\.patch$`));
    const bytes = readFileSync(safe(patch.path));
    assert.equal(createHash('sha256').update(bytes).digest('hex'), patch.sha256, patch.path);
    assert.ok(bytes.toString().startsWith(`From ${patch.commit} `));
    assert.ok(execute(['git', 'apply', '--numstat', safe(patch.path)], path.resolve(directory, '../..')).trim());
    const lines = bytes.toString().split('\n');
    const findings = privacyFindings(bytes.toString());
    const exceptions = manifest.privacyExceptions?.[patch.path] ?? [];
    for (const exception of exceptions) {
      assert.ok(exception.reason && findings.some(finding => finding.line === exception.line && finding.code === exception.code));
      assert.equal(createHash('sha256').update(lines[exception.line - 1]).digest('hex'), exception.lineSha256);
    }
    assert.deepEqual(findings.filter(finding => !exceptions.some(exception => exception.line === finding.line && exception.code === finding.code)), [], patch.path);
  }
  assert.equal(manifest.patches.at(-1).commit, manifest.head);
  for (const [file, digest] of Object.entries(manifest.files)) {
    const bytes = readFileSync(safe(file));
    assert.equal(createHash('sha256').update(bytes).digest('hex'), digest, file);
    if (file.startsWith('samples/native/')) assert.deepEqual(privacyFindings(bytes.toString()), [], file);
  }
  const native = readdirSync(path.join(directory, 'samples/native'));
  assert.ok(native.length, 'native sample required');
  const samples = readdirSync(path.join(directory, 'samples/asr')).filter(name => name.endsWith('.jsonl'));
  assert.ok(samples.length, 'ASR sample required');
  for (const name of samples) {
    const filename = path.join(directory, 'samples/asr', name);
    const result = validateFile(filename);
    assert.equal(result.valid, true, JSON.stringify(result.diagnostics));
    assert.deepEqual(privacyFindings(readFileSync(filename, 'utf8')), [], name);
    const header = JSON.parse(readFileSync(filename, 'utf8').split('\n')[0]);
    assert.equal(header.agent.name, manifest.agent);
    console.log(`${manifest.agent}/${name}: ${result.diagnostics.length} validator warning(s), zero errors`);
  }
  return manifest;
}

export async function checkPackage(url) {
  const directory = fileURLToPath(url);
  const manifest = inspectPackage(path.resolve(directory));
  for (const command of manifest.checks) {
    process.stdout.write(execute(command, directory, { ...process.env, ASR_UPSTREAM_AGENT: manifest.agent }));
  }
}

export async function reproducePackage(url, checkout) {
  assert.ok(checkout, 'usage: node upstream/AGENT/reproduce.mjs UPSTREAM_CHECKOUT');
  const directory = path.resolve(fileURLToPath(url));
  const manifest = inspectPackage(directory);
  const scratch = mkdtempSync(path.join(tmpdir(), 'asr-patch-replay-'));
  try {
    const env = { ...process.env, GIT_INDEX_FILE: path.join(scratch, 'index') };
    execute(['git', 'read-tree', manifest.base], checkout, env);
    for (const patch of manifest.patches) execute(['git', 'apply', '--cached', path.join(directory, patch.path)], checkout, env);
    const actual = execute(['git', 'write-tree'], checkout, env).trim();
    const expected = execute(['git', 'rev-parse', `${manifest.head}^{tree}`], checkout).trim();
    assert.equal(actual, expected, 'replayed series must reproduce the committed source tree');
    await checkPackage(url);
    console.log(`${manifest.agent}: pinned patch replay and sample checks passed`);
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
}
