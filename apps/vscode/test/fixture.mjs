import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export function validateFixture(file) {
  const root = fileURLToPath(new URL('../../../', import.meta.url));
  const result = JSON.parse(execFileSync(process.execPath, [path.join(root, 'tools/validator/bin/asr-validate.js'), '--json', file], { cwd: root, encoding: 'utf8' }));
  assert.equal(result.errors, 0); assert.equal(result.warnings, 0);
}
export async function fixture(dir) {
  const repo = path.join(dir, 'repo with spaces');
  const store = path.join(dir, 'sessions');
  await mkdir(repo, { recursive: true }); await mkdir(store, { recursive: true });
  const gitAt = (at, ...args) => execFileSync('git', ['-C', repo, ...args], { encoding: 'utf8', env: { ...process.env, GIT_CONFIG_GLOBAL: '/dev/null', GIT_CONFIG_NOSYSTEM: '1', ...(at ? { GIT_AUTHOR_DATE: at, GIT_COMMITTER_DATE: at } : {}) } }).trim();
  const git = (...args) => gitAt(null, ...args);
  git('init', '-q'); git('config', 'user.name', 'Synthetic'); git('config', 'user.email', 'synthetic@example.com');
  const file = path.join(repo, 'parser.ts');
  const before = 'export const value = 1;\nexport const stable = true;\n';
  const after = 'export const value = 7;\nexport const stable = true;\n';
  await writeFile(file, before); git('add', '.'); gitAt('2026-11-01T11:59:00Z', 'commit', '-qm', 'Synthetic baseline');
  await writeFile(file, after); git('add', '.'); gitAt('2026-11-01T12:01:00Z', 'commit', '-qm', 'Synthetic change');
  const commit = git('rev-parse', 'HEAD');
  const records = [
    { type: 'session', id: 'header', formatVersion: '0.1', agent: { name: 'com.example.agent' }, sessionId: 'editor:7', producer: { name: 'synthetic', version: '1', method: 'native' }, cwd: repo, repos: [{ path: repo }], missing: ['usage'] },
    { type: 'message', id: 'prompt', turnId: 'turn', role: 'user', author: 'human', origin: 'prompt', content: [{ type: 'text', text: 'Use seven. <script>globalThis.injected=true</script> [run](command:workbench.action.closeWindow) https://example.invalid/private' }] },
    { type: 'inference', id: 'model', model: { id: 'synthetic-served' } },
    { type: 'tool_call', id: 'call', callId: 'edit', inferenceId: 'model', turnId: 'turn', name: 'replace', kind: 'edit' },
    { type: 'approval', id: 'approval', callId: 'edit', decision: 'approved', by: 'user', scope: 'once', native: { large: 'EXACT_NUMBER' } },
    { type: 'tool_result', id: 'result', callId: 'edit', status: 'completed' },
    { type: 'file_change', id: 'change', ts: '2026-11-01T12:00:00Z', path: file, op: 'modify', status: 'applied', callId: 'edit', before: { text: before }, after: { text: after } },
    { type: 'tool_call', id: 'commit-call', callId: 'commit', name: 'git', kind: 'execute' },
    { type: 'tool_result', id: 'commit-result', callId: 'commit', status: 'completed' },
    { type: 'vcs', id: 'commit', action: 'commit', status: 'completed', evidence: 'observed', callId: 'commit', repo, commit },
    { type: 'session_info', id: 'loss', missing: ['approvals'] },
    { type: 'gap', id: 'gap', ts: '2026-11-01T12:02:00Z', reason: 'not_recorded', count: 1 }
  ];
  const session = path.join(store, 'session.jsonl');
  await writeFile(session, records.map(r => JSON.stringify(r).replace('"EXACT_NUMBER"', '9007199254740993')).join('\n') + '\n');
  validateFixture(session);
  const value = { repo, file, store, session, reference: 'com.example.agent:editor%3A7', commit };
  await writeFile(path.join(dir, 'fixture.json'), JSON.stringify(value));
  return value;
}
if (process.argv[1] === fileURLToPath(import.meta.url)) await fixture(path.resolve(process.argv[2]));
