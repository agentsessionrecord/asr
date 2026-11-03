import assert from 'node:assert/strict';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { checkToolDocs, toolJob } from '../check-tool-docs.mjs';
import { repositoryRoot } from '../lib/files.mjs';

function setup(t) {
  const root = mkdtempSync(path.join(tmpdir(), 'asr-tool-docs-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const jobs = ['index', 'convert', 'record', 'collect', 'view', 'export', 'import', 'patch'];
  const write = (file, text) => {
    mkdirSync(path.dirname(path.join(root, file)), { recursive: true });
    writeFileSync(path.join(root, file), text);
  };
  const entry = { id: 'converter-test', name: 'Test converter', kind: 'converter', path: 'crates/converter/src/test.rs', status: 'built', liveTestStatus: 'not-live-tested' };
  write('registry.json', JSON.stringify({ entries: [entry] }));
  write(entry.path, '');
  write('crates/converter/README.md', '# Test converter\n');
  const row = '| [Test converter](https://github.com/agentsessionrecord/asr/blob/main/crates/converter/README.md) | `not-live-tested` |\n';
  for (const job of jobs) write(`site/pages/tools/${job}.mdx`, job === 'convert' ? row : '');
  const navigate = pages => write('site/pages/docs.json', JSON.stringify({ navigation: { tabs: [{ groups: [{ pages }] }] } }));
  navigate(jobs.map(job => `tools/${job}`));
  return { root, write, row, navigate, entry };
}

test('current registry is covered by navigable job pages and README links', () => {
  const result = checkToolDocs(repositoryRoot);
  assert.ok(result.entries > 0);
  assert.deepEqual(result.problems, []);
});

test('catalog detects an absent row, a stale status and a missing README', t => {
  const { root, write, row } = setup(t);
  assert.deepEqual(checkToolDocs(root).problems, []);
  write('site/pages/tools/convert.mdx', '');
  assert.match(checkToolDocs(root).problems.join('\n'), /converter-test: missing README row/);
  write('site/pages/tools/convert.mdx', row.replace('`not-live-tested`', '`passed`'));
  assert.match(checkToolDocs(root).problems.join('\n'), /converter-test: stale live-test status/);
  rmSync(path.join(root, 'crates/converter/README.md'));
  assert.match(checkToolDocs(root).problems.join('\n'), /converter-test: missing nearby README/);
});

test('catalog detects missing pages, navigation and local README links', t => {
  const { root, write, navigate } = setup(t);
  navigate(['tools/convert']);
  rmSync(path.join(root, 'site/pages/tools/patch.mdx'));
  write('crates/converter/README.md', '[profile](MISSING.md)\n');
  const problems = checkToolDocs(root).problems.join('\n');
  assert.match(problems, /tools\/patch: missing navigation entry/);
  assert.match(problems, /tools\/patch: missing page/);
  assert.match(problems, /missing link target MISSING.md/);
});

test('repository links resolve locally and each shared README row is required', t => {
  const { root, write, row, entry } = setup(t);
  write('registry.json', JSON.stringify({ entries: [entry, { ...entry, id: 'converter-second', name: 'Second converter' }] }));
  write('site/pages/tools/convert.mdx', row + '\n[extra](https://github.com/agentsessionrecord/asr/blob/main/MISSING.md)\n');
  const problems = checkToolDocs(root).problems.join('\n');
  assert.match(problems, /converter-second: missing README row/);
  assert.match(problems, /missing link target https:\/\/github.com/);
});

test('root README cannot replace a missing tool README with either root spelling', t => {
  const { root, write } = setup(t);
  write('README.md', '# Repository\n');
  rmSync(path.join(root, 'crates/converter/README.md'));
  for (const directory of [root, root + path.sep]) {
    assert.match(checkToolDocs(directory).problems.join('\n'), /converter-test: missing nearby README/);
  }
});

test('security guidance must be linked by the catalog and have valid local links', t => {
  const { root, write } = setup(t);
  write('SECURITY.md', '[details](MISSING.md)\n');
  let problems = checkToolDocs(root).problems.join('\n');
  assert.match(problems, /tools\/index: missing security guidance link/);
  assert.match(problems, /SECURITY.md: missing link target MISSING.md/);
  write('site/pages/tools/index.mdx', '[Security](https://github.com/agentsessionrecord/asr/blob/main/SECURITY.md)\n');
  write('SECURITY.md', '[Tool](crates/converter/README.md)\n');
  assert.deepEqual(checkToolDocs(root).problems, []);
});

test('each integration route has a job and samples need no tool row', t => {
  for (const [kind, job] of Object.entries({ converter: 'convert', plugin: 'record', recorder: 'record', library: 'record', importer: 'import', exporter: 'export', app: 'view', patch: 'patch', tool: 'index' })) {
    assert.equal(toolJob({ kind }), job);
  }
  assert.equal(toolJob({ id: 'asr-collect', kind: 'tool' }), 'collect');
  assert.equal(toolJob({ id: 'asr-receive', kind: 'tool' }), 'collect');
  assert.equal(toolJob({ id: 'asr-convert', kind: 'library' }), 'convert');
  assert.equal(toolJob({ id: 'vendor-importer-core', kind: 'library' }), 'import');
  const { root, write, entry } = setup(t);
  write('registry.json', JSON.stringify({ entries: [entry, { id: 'sample', kind: 'sample', status: 'built' }] }));
  assert.deepEqual(checkToolDocs(root).problems, []);
});

test('root README introduces tools and links their local setup instructions', () => {
  const readme = readFileSync(path.join(repositoryRoot, 'README.md'), 'utf8');
  const section = readme.split('## Tools\n')[1]?.split('\n## ')[0];
  assert.ok(section);
  for (const target of ['site/pages/tools/', 'crates/asr-cli/README.md', 'plugins/README.md',
    'recorders/', 'apps/viewer/README.md', 'exporters/', 'upstream/README.md']) {
    assert.ok(section.includes(`](${target})`), target);
    assert.ok(existsSync(path.join(repositoryRoot, target)), target);
  }
});
