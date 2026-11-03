import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { repositoryRoot } from '../lib/files.mjs';

function setup(t, files = []) {
  const root = mkdtempSync(path.join(tmpdir(), 'asr-ci-test-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  mkdirSync(path.join(root, 'scripts'));
  mkdirSync(path.join(root, 'bin'));
  copyFileSync(path.join(repositoryRoot, 'scripts/ci.sh'), path.join(root, 'scripts/ci.sh'));
  for (const file of files) {
    mkdirSync(path.dirname(path.join(root, file)), { recursive: true });
    writeFileSync(path.join(root, file), '');
  }
  const stub = `#!/usr/bin/env bash
name=\$\{0##*/\}
printf '%s %s\\n' "$name" "$*" >> "$ASR_CI_TEST_LOG"
if [[ -n \$\{ASR_CI_TEST_FAILURE:-\} && "$name $*" == "$ASR_CI_TEST_FAILURE"* ]]; then exit 23; fi
`;
  for (const name of ['node', 'pnpm', 'python3', 'cargo', 'uv', 'go', 'git']) {
    writeFileSync(path.join(root, 'bin', name), stub, { mode: 0o755 });
  }
  function run(failure = '') {
    const result = spawnSync('bash', [path.join(root, 'scripts/ci.sh')], {
      cwd: tmpdir(), encoding: 'utf8',
      env: { ...process.env, PATH: `${root}/bin:${process.env.PATH}`, ASR_CI_TEST_LOG: `${root}/commands`, ASR_CI_TEST_FAILURE: failure },
    });
    assert.ifError(result.error);
    return { ...result, commands: readFileSync(path.join(root, 'commands'), 'utf8') };
  }
  return { root, run };
}

test('CI skips empty language trees, including an empty Cargo workspace', (t) => {
  const { run } = setup(t, ['Cargo.toml', 'crates/README.md', 'packages/README.md', 'python/README.md', 'go/go.mod']);
  const result = run();
  assert.equal(result.status, 0, result.stderr + result.stdout);
  for (const section of ['Rust generated types', 'Rust format', 'Rust clippy', 'Rust tests', 'Rust corpus and performance harness tests', 'Native JSONL converter goldens', 'Cursor, Gemini, Vibe, Mux and fx goldens', 'Rust converter goldens', 'Collector CLI build', 'Generated blame histories', 'Blame end-to-end', 'Collector watch checks', 'Collector MinIO', 'pnpm package tests', 'Python tests', 'Go tests']) {
    assert.ok(result.stdout.split('\n').some((line) => line.startsWith(section) && line.includes('SKIP')), section);
  }
  assert.doesNotMatch(result.commands, /^(cargo|uv|go|pnpm) /m);
  assert.match(result.commands, /node scripts\/check-privacy.mjs/);
  assert.match(result.stdout, /0 failed check\(s\)/);
});

const populated = ['scripts/test_live_provider.py', 'tools/validator/package.json', 'whitepaper/build.mjs', 'site/build.mjs', 'registry.json', 'scripts/check-tool-docs.mjs', 'pnpm-workspace.yaml', 'scripts/test/synthetic.test.mjs', 'crates/core/Cargo.toml', 'packages/writer/package.json', 'python/agent_session_record/pyproject.toml', 'go/asr/asr.go'];

test('CI dispatches every populated tree and builds the PDF before the strict site', (t) => {
  const { run } = setup(t, populated);
  const result = run();
  assert.equal(result.status, 0, result.stderr + result.stdout);
  for (const command of [
    'pnpm --dir tools/validator run ci',
    'node whitepaper/build.mjs', 'node site/build.mjs --strict',
    'python3 -m unittest discover -s scripts -p test_*.py',
    'node scripts/check-registry.mjs', 'node scripts/check-tool-docs.mjs', 'node --test scripts/test/synthetic.test.mjs',
    'pnpm --recursive --if-present run check:generated',
    'python3 crates/asr-core/generate.py --check',
    'cargo build -p asr-cli --locked',
    'python3 crates/asr-cli/scripts/check-generated-blame.py --binary target/debug/asr --histories 2000 --seed 600601 --seconds 900',
    'python3 crates/asr-cli/scripts/check-blame.py --binary target/debug/asr',
    'python3 crates/asr-collect/scripts/check-local.py --binary target/debug/asr',
    'cargo fmt --all --check', 'cargo clippy --workspace --all-targets -- -D warnings', 'cargo test --workspace',
    'python3 -m unittest discover -s crates/asr-convert/scripts -p test_*.py',
    'node tools/validator/bin/asr-validate.js --summary crates/asr-convert/tests/golden',
    'node tools/validator/bin/asr-validate.js --summary crates/asr-convert/tests/jsonl-b/golden',
    'node tools/validator/bin/asr-validate.js --summary crates/asr-convert/tests/golden-w1-conv-a',
    "pnpm --recursive --filter ./packages/** --if-present run test",
    'uv run --all-packages pytest python', 'go test ./...',
    'git diff --check', 'git diff --cached --check',
    'git -c core.whitespace=blank-at-eol,blank-at-eof diff --check 4b825dc642cb6eb9a060e54bf8d69288fbee4904 HEAD',
  ]) assert.ok(result.commands.includes(command + '\n'), command);
  assert.ok(result.commands.indexOf('node whitepaper') < result.commands.indexOf('node site'));
  assert.ok(result.commands.indexOf('python3 crates/asr-core/generate.py') < result.commands.indexOf('cargo fmt'));
  assert.match(result.stdout, /Go format\s+\| SKIP/);
  assert.match(result.stdout, /zed native export patch\s+\| SKIP\s+\| missing upstream\/zed\/check.mjs/);
  assert.equal(new Set(result.commands.trim().split('\n')).size, result.commands.trim().split('\n').length);

});

test('CI preserves failures, runs later checks and reports each result', (t) => {
  const { run } = setup(t, populated);
  const result = run('cargo clippy');
  assert.equal(result.status, 1);
  assert.match(result.stdout, /Rust clippy\s+\| FAIL\s+\| exit 23/);
  assert.match(result.stdout, /Rust tests\s+\| PASS/);
  assert.match(result.stdout, /1 failed check\(s\)/);
  assert.match(result.commands, /node scripts\/check-privacy.mjs/);
});

test('CI bounds generated histories and preserves a timeout as a failure', (t) => {
  const { root, run } = setup(t, populated);
  writeFileSync(path.join(root, 'bin', 'timeout'), `#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$ASR_CI_TEST_LOG"
[[ "$1" == --kill-after=10s && "$2" == 930s ]] || exit 23
exit 124
`, { mode: 0o755 });
  const result = run();
  assert.equal(result.status, 1);
  assert.ok(result.commands.includes('--kill-after=10s 930s python3 crates/asr-cli/scripts/check-generated-blame.py --binary target/debug/asr --histories 2000 --seed 600601 --seconds 900\n'));
  assert.match(result.stdout, /Generated blame histories\s+\| FAIL\s+\| exit 124/);
  assert.match(result.stdout, /Blame end-to-end\s+\| PASS/);
  assert.match(result.stdout, /Fixture privacy\s+\| PASS/);
  assert.match(result.stdout, /1 failed check\(s\)/);
});

test('CI reports catalog failure and continues with script tests', (t) => {
  const { run } = setup(t, populated);
  const result = run('node scripts/check-tool-docs.mjs');
  assert.equal(result.status, 1);
  assert.match(result.stdout, /Tool documentation\s+\| FAIL\s+\| exit 23/);
  assert.match(result.stdout, /CI script tests\s+\| PASS/);
  assert.match(result.stdout, /1 failed check\(s\)/);
});

test('CI does not treat an installed dependency or generated cache as a source tree', (t) => {
  const { run } = setup(t, ['crates/target/cache/Cargo.toml', 'python/.venv/lib/cache.py', 'packages/node_modules/tool/package.json', 'go/vendor/tool/example.go']);
  const result = run();
  assert.equal(result.status, 0, result.stderr + result.stdout);
  assert.doesNotMatch(result.commands, /^(cargo|uv|go|pnpm) /m);
});


test('CI reports Go formatting failures and continues to later checks', (t) => {
  const { root, run } = setup(t, ['scripts/check-go-format.sh']);
  writeFileSync(path.join(root, 'scripts/check-go-format.sh'),
    '#!/usr/bin/env bash\nprintf "library-check\\n" >> "$ASR_CI_TEST_LOG"\nexit 23\n');
  const result = run();
  assert.equal(result.status, 1);
  assert.match(result.commands, /library-check/);
  assert.match(result.stdout, /Go format\s+\| FAIL\s+\| exit 23/);
  assert.match(result.stdout, /Fixture privacy\s+\| PASS/);
  assert.match(result.stdout, /1 failed check\(s\)/);
});

test('every optional suite reports a missing entry point with a reason', (t) => {
  const { run } = setup(t);
  const result = run();
  const source = readFileSync(path.join(repositoryRoot, 'scripts/ci.sh'), 'utf8');
  for (const match of source.matchAll(/^run_file '([^']+)' (\S+)/gm)) {
    const row = result.stdout.split('\n').find(line => line.startsWith(match[1]) && line.includes('| SKIP'));
    assert.ok(row?.includes(`missing ${match[2]}`), match[1]);
  }
});


test('CI preserves recorder and importer suites and the isolated observability environment', (t) => {
  const { run } = setup(t, ['recorders/acp/pyproject.toml', 'recorders/envoy/pyproject.toml', 'importers/vendor-core/pyproject.toml', 'exporters/evals/pyproject.toml']);
  const result = run();
  assert.equal(result.status, 0, result.stderr + result.stdout);
  for (const command of [
    'uv run --all-packages pytest recorders/acp/tests recorders/envoy/tests',
    'uv run --all-packages pytest importers/vendor-core/tests importers/anthropic-compliance/tests importers/openai-codex-logs/tests importers/copilot/tests importers/entire/tests',
    'uv run --isolated --package asr-phoenix --with pytest>=8.3,<10 --with-editable exporters/langfuse --with-editable exporters/braintrust pytest exporters/evals/tests exporters/phoenix/tests',
  ]) assert.ok(result.commands.split('\n').includes(command), command);
});
