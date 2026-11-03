import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { privacyFindings } from '../../scripts/check-privacy.mjs';
import { checkWriting } from '../../scripts/check-writing.mjs';
import { validateFile } from '../../tools/validator/src/index.js';
import { formatAgentSession } from './plugin/dist/format.js';

export function checkPluginPackage() {
  const directory = dirname(fileURLToPath(import.meta.url));
  const manifest = JSON.parse(readFileSync(join(directory, 'manifest.json'), 'utf8'));
  assert.equal(manifest.schemaVersion, 1);
  assert.equal(manifest.agent, 'deepseek-harness');
  assert.equal(manifest.kind, 'plugin');
  assert.match(manifest.base, /^[a-f0-9]{40}$/);
  assert.equal(manifest.head, manifest.base);
  assert.deepEqual(manifest.patches, []);
  const files = (folder, prefix = '') => readdirSync(folder, { withFileTypes: true }).flatMap(entry => {
    if (entry.name === 'node_modules' || entry.name.endsWith('.tgz')) return [];
    assert.ok(entry.isDirectory() || entry.isFile());
    const name = prefix + entry.name;
    return entry.isDirectory() ? files(join(folder, entry.name), name + '/') : [name];
  });
  assert.deepEqual(files(directory).filter(name => name !== 'manifest.json').sort(), Object.keys(manifest.files).sort());
  for (const [name, digest] of Object.entries(manifest.files)) {
    assert.ok(!name.split('/').includes('..'));
    const bytes = readFileSync(join(directory, name));
    assert.equal(createHash('sha256').update(bytes).digest('hex'), digest, name);
    assert.deepEqual(privacyFindings(bytes.toString()), [], name);
  }
  for (const name of ['README.md', 'PROPOSAL.md', 'plugin/README.md']) {
    assert.deepEqual(checkWriting(readFileSync(join(directory, name), 'utf8'), name), []);
  }
  const source = JSON.parse(readFileSync(join(directory, 'samples/native/native.json'), 'utf8'));
  const output = formatAgentSession(source.session, source.events, source.inheritedEventCount);
  const sample = join(directory, 'samples/asr/session.jsonl');
  assert.equal(output, readFileSync(sample, 'utf8'));
  assert.ok(!output.includes('SYNTHETIC-OPAQUE'));
  const result = validateFile(sample);
  assert.equal(result.valid, true, JSON.stringify(result.diagnostics));
  const metadata = JSON.parse(readFileSync(join(directory, 'plugin/package.json'), 'utf8'));
  assert.ok(metadata.keywords.includes('dsh-plugin'));
  assert.equal(metadata.name, 'dsh-plugin-asr-export');
  assert.equal(metadata.license, 'Apache-2.0');
  assert.match(readFileSync(join(directory, 'plugin/LICENSE'), 'utf8'), /Apache License/);
  assert.equal(metadata.dsh.bundle.patch, './cordis.patch.yml');
  console.log(`deepseek-harness: plugin digests and native fixture passed, ${result.diagnostics.length} validator warnings, zero errors`);
  return manifest;
}
if (process.argv[1] === fileURLToPath(import.meta.url)) checkPluginPackage();
