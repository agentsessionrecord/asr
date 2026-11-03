import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { checkRegistry } from '../check-registry.mjs';
import { isFixtureFile, privacyFindings, scanPrivacy } from '../check-privacy.mjs';
import { checkWriting, scanWriting } from '../check-writing.mjs';
import { repositoryRoot } from '../lib/files.mjs';

const schema = JSON.parse(readFileSync(path.join(repositoryRoot, 'schema/registry.schema.json'), 'utf8'));

function temporary(t) {
  const root = mkdtempSync(path.join(tmpdir(), 'asr-check-test-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  return root;
}

function entry(overrides = {}) {
  return {
    id: 'test-tool', name: 'Test tool', kind: 'tool', path: 'tools/test',
    language: 'JavaScript', status: 'planned', location: 'tools/test',
    liveTestStatus: 'not-live-tested', ...overrides,
  };
}

const registry = (...entries) => ({ schemaVersion: 1, entries });

test('registry checks identity, required fields, path safety and known states', (t) => {
  const root = temporary(t);
  assert.deepEqual(checkRegistry(registry(entry()), schema, root), []);
  assert.match(checkRegistry(registry(entry(), entry()), schema, root).join(), /Duplicate registry ID/);
  for (const path of ['../outside', '/absolute', 'tools/../outside', 'tools/./test', 'tools\\test']) {
    assert.ok(checkRegistry(registry(entry({ path, location: path })), schema, root).length);
  }
  for (const change of [{ language: undefined }, { status: 'ready-ish' }, { liveTestStatus: 'maybe' }]) {
    assert.ok(checkRegistry(registry(entry(change)), schema, root).length);
  }
});

test('registry requires local implementation paths and external provenance', (t) => {
  const root = temporary(t);
  assert.match(checkRegistry(registry(entry({ status: 'built' })), schema, root).join(), /does not exist/);
  mkdirSync(path.join(root, 'tools/test'), { recursive: true });
  assert.deepEqual(checkRegistry(registry(entry({ status: 'built' })), schema, root), []);
  assert.match(checkRegistry(registry(entry({ location: 'elsewhere' })), schema, root).join(), /must equal path/);
  const external = entry({ status: 'elsewhere', location: 'https://example.org/export', revision: 'a'.repeat(40), notes: 'Not imported.' });
  assert.deepEqual(checkRegistry(registry(external), schema, root), []);
  assert.ok(checkRegistry(registry({ ...external, location: 'unknown' }), schema, root).length);
  assert.ok(checkRegistry(registry({ ...external, revision: undefined }), schema, root).length);
  assert.ok(checkRegistry(registry(entry({ liveTestStatus: 'passed' })), schema, root).length);
});

test('privacy checks report locations and codes without retaining matching values', () => {
  const syntheticSecret = 'a'.repeat(30);
  const values = [
    ['provider-token', 'sk-' + 'a'.repeat(24)],
    ['cloud-key', 'AKIA' + 'A'.repeat(16)],
    ['bearer-token', 'Bearer ' + 'a'.repeat(30)],
    ['jwt', 'eyJ' + 'a'.repeat(16) + '.' + 'b'.repeat(16) + '.' + 'c'.repeat(16)],
    ['private-home-path', ['', 'home', 'private-user', 'data'].join('/')],
    ['private-home-path', ['C:', 'Users', 'private-user', 'data'].join('\\')],
    ['sensitive-phrase', ['master', 'password'].join(' ')],
    ['account-id', 'acct-' + 'a'.repeat(16)],
    ['sensitive-assignment', JSON.stringify({ account_id: String(1234567890123456) })],
    ['sensitive-assignment', JSON.stringify({ api_key: syntheticSecret })],
  ];
  for (const [code, value] of values) {
    const findings = privacyFindings('safe\n' + value);
    assert.ok(findings.some((finding) => finding.code === code && finding.line === 2), code);
    assert.ok(!JSON.stringify(findings).includes(value));
  }
  for (const value of ['example', 'test-token', '[redacted]', '<API_KEY>', '${API_KEY}']) {
    assert.deepEqual(privacyFindings(JSON.stringify({ api_key: value })), []);
  }
  assert.deepEqual(privacyFindings(JSON.stringify({ sessionKey: 'agent:main:session:synthetic' })), []);
});

test('privacy scan includes nested samples and fixtures in every language tree', (t) => {
  const root = temporary(t);
  for (const file of ['samples/agent/native/data.json', 'samples/agent/native/node_modules/data', 'crates/core/tests/fixtures/dist/log.jsonl', 'packages/test/__fixtures__/data', 'python/lib/tests/testdata/data', 'go/asr/testdata/data', 'tools/new/fixture.json', 'upstream/agent/samples/native/data.json', 'upstream/agent/samples/asr/session.jsonl']) {
    assert.ok(isFixtureFile(file), file);
    mkdirSync(path.dirname(path.join(root, file)), { recursive: true });
    writeFileSync(path.join(root, file), 'sk-' + 'a'.repeat(24));
  }
  mkdirSync(path.join(root, 'node_modules/dependency/fixtures'), { recursive: true });
  writeFileSync(path.join(root, 'node_modules/dependency/fixtures/data'), 'sk-' + 'a'.repeat(24));
  const result = scanPrivacy(root);
  assert.equal(result.files, 9);
  assert.equal(result.findings.length, 9);
});

test('writing rules check prose but preserve code, URLs, metadata and comments', () => {
  const text = ['---', 'title: "no longer"', '---', 'Plain English.', '```sh', 'echo "no longer;"', '```', '`no longer;`', '[source](https://example.org/no-model)', '<!-- no longer; -->'].join('\n');
  assert.deepEqual(checkWriting(text, 'README.md'), []);
  assert.deepEqual(checkWriting('This was removed; use the new file.', 'README.md'), [
    { line: 1, code: 'prose-punctuation' }, { line: 1, code: 'writing-rule' },
  ]);
  assert.ok(checkWriting('One → two — three.', 'README.md').length);
  const name = ['T3', 'Code'].join(' ');
  assert.equal(checkWriting(name, 'README.md')[0].code, 'agent-name');
  assert.deepEqual(checkWriting(`| ${name} |`, 'agents/index.md'), []);
  assert.ok(checkWriting(name, 'agents/index.md').length);
  assert.equal(checkWriting(name, 'schema/registry.schema.json')[0].code, 'agent-name');
});

test('public text checks include JSON, source, links, code spans and fenced blocks', (t) => {
  const root = temporary(t);
  const tool = ['c', 'tx'].join('');
  const agent = ['T3', 'Code'].join(' ');
  const home = ['', 'home', 'private-user', 'source'].join('/');
  const text = JSON.stringify({ name: agent, location: home, url: `https://example.org/${tool}` });
  writeFileSync(path.join(root, 'registry.json'), text);
  writeFileSync(path.join(root, 'source.py'), `# ${agent}\n`);
  writeFileSync(path.join(root, 'README.md'), `\`${tool}\`\n\`\`\`sh\n${home}\n\`\`\`\n[source](https://example.org/${tool})\n`);
  const result = scanWriting(root);
  assert.equal(result.files, 3);
  for (const file of ['registry.json', 'source.py', 'README.md']) assert.ok(result.findings.some((f) => f.file === file));
  for (const code of ['agent-name', 'internal-name', 'local-path']) assert.ok(result.findings.some((f) => f.code === code));
  assert.ok(!JSON.stringify(result.findings).includes(home));
});

test('public examples reject environment literals and internal reports', (t) => {
  const values = ['build ' + 'governor', 'http://127.0.0.1:' + '83' + '17/v1',
    'gpt-6.1-' + 'sol', 'gpt-6-' + 'luna', 'hai' + 'ku',
    ['local', 'proxy'].join(' '), ['local', 'model', 'proxy'].join(' ')];
  for (const file of ['README.md', 'guide.mdx', 'config.example.yaml', 'tests/e2e/providers.py',
    'plugins/agent/scripts/live-test.mjs', 'scripts/check.sh', 'scripts/config.ts']) {
    for (const value of values) {
      assert.ok(checkWriting('```sh\n' + value + '\n```', file)
        .some(f => f.code === 'local-environment'), file);
    }
    assert.deepEqual(checkWriting('http://127.0.0.1:PORT/v1 --model MODEL', file), []);
  }
  for (const file of ['apps/editor/BUILD-' + ['REPORT', 'md'].join('.'), 'SPEC-' + ['FEEDBACK', 'md'].join('.'),
    ['reviews', 'review.md'].join('/')]) {
    assert.ok(checkWriting('Private material.', file).some(f => f.code === 'internal-report-file'));
  }
  for (const text of ['Task: ' + '`fix`', 'Branch: ' + '`codex/fix`',
    '[evidence](' + ['reviews', 'review.md'].join('/') + ')']) {
    assert.ok(checkWriting(text, 'README.md').some(f => f.code === 'internal-report-reference'));
  }
  const root = temporary(t);
  mkdirSync(path.join(root, 'reviews'));
  writeFileSync(path.join(root, 'reviews', 'note.md'), 'Private material.');
  assert.ok(scanWriting(root).findings.some(f => f.code === 'internal-report-file'));
});

test('passed registry status rejects old code and offline-only evidence', (t) => {
  const root = temporary(t);
  for (const liveTestNotes of ['Prior revision: agent run passed.',
    'Synthetic local Git repositories exercise checks.',
    'Local example sessions pass. No agent inference is needed.',
    'Only unit tests passed.', 'Source CLI ran. The exporter was then refined.']) {
    assert.match(checkRegistry(registry(entry({ liveTestStatus: 'passed', liveTestNotes })), schema, root).join(),
      /live run of the current implementation/);
    assert.deepEqual(checkRegistry(registry(entry({ liveTestStatus: 'partial', liveTestNotes })), schema, root), []);
  }
  assert.deepEqual(checkRegistry(registry(entry({ liveTestStatus: 'passed',
    liveTestNotes: 'Current source CLI completed an isolated session and exported its native history.' })), schema, root), []);
});

test('endpoint wording catches qualifiers and wrapped prose with source line numbers', () => {
  for (const qualifier of ['', 'model ', 'OpenAI-compatible ', 'Gemini-compatible ', 'Responses ', 'LiteLLM ']) {
    for (const separator of [' ', '\n', '\r\n', '\n+']) {
      const text = 'Intro.\nA ' + 'local ' + qualifier.trimEnd() + separator + 'pro' + 'xy serves requests.';
      for (const file of ['README.md', 'upstream/agent/patches/export.patch', 'registry.json']) {
        assert.deepEqual(checkWriting(text, file), [{ line: 2, code: 'local-environment' }]);
      }
    }
  }
  const phrase = ['local', 'model', 'pro' + 'xy'].join('\n');
  assert.deepEqual(checkWriting(phrase + '\n\n' + phrase, 'README.md'), [
    { line: 1, code: 'local-environment' }, { line: 5, code: 'local-environment' },
  ]);
  assert.deepEqual(checkWriting('A local endpoint.\nA remote proxy.', 'README.md'), []);
});
