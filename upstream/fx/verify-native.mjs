import { spawnSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const directory = fileURLToPath(new URL('.', import.meta.url));
const repository = resolve(directory, '../..');
const checkout = resolve(process.argv[2]);
const scratch = mkdtempSync(join(tmpdir(), 'asr-refresh-checks-'));
const manifest = JSON.parse(readFileSync(join(directory, 'manifest.json'), 'utf8'));
const commands = [
  [
    "{zig}",
    "fmt",
    "--check",
    "src/core/session/agent_session.zig",
    "src/core/cli/cli_surface.zig",
    "src/builtins/commands.zig",
    "build.zig"
  ],
  [
    "{zig}",
    "build",
    "test-agent-session"
  ],
  [
    "{zig}",
    "build"
  ],
  ["bun", "test", "tests/e2e/sessions.test.ts", "-t", "fx ask saves to v2, resumes by id and by last, and never writes v1"]
];
const results = [];
const replace = value => value.replaceAll('{package}', directory).replaceAll('{checkout}', checkout).replaceAll('{zig}', process.env.ASR_ZIG ?? 'zig');
function run(command, cwd = checkout) {
  const actual = command.map(replace);
  console.log(JSON.stringify({ command }));
  const result = spawnSync(actual[0], actual.slice(1), { cwd, encoding: 'utf8', timeout: 600000, maxBuffer: 16 * 1024 * 1024 });
  results.push({ command: command.map(value => value.replaceAll(directory, '{package}').replaceAll(checkout, '{checkout}').replaceAll(scratch, '{scratch}').replaceAll(repository, '{repository}')), exit: result.status, error: result.error?.code ?? null });
  if (result.status !== 0) console.log((result.stdout + result.stderr).slice(-5000));
  return result;
}
try {
  for (const command of commands) run(command);
  run(['python3', '{package}/reproduce.py', '{checkout}']);
  const validation = run(['node', 'tools/validator/bin/asr-validate.js', '--json', join(directory, 'samples/asr/session.jsonl')], repository);
  let validator;
  try { const data = JSON.parse(validation.stdout); validator = { errors: data.errors, warnings: data.warnings }; } catch { validator = { status: 'unavailable' }; }
  writeFileSync(join(directory, 'verification.json'), JSON.stringify({ date: '2026-11-03', sourceBase: manifest.base, status: results.every(result => result.exit === 0) ? 'passed' : 'blocked', checks: results, validator, liveTest: 'not-run-for-refreshed-source' }, null, 2) + '\n');
  if (results.some(result => result.exit !== 0)) process.exitCode = 1;
} finally { rmSync(scratch, { recursive: true, force: true }); }
