import assert from 'node:assert/strict';
import { readFileSync, mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';

const checkout = resolve(process.argv[2]);
const directory = fileURLToPath(new URL('./', import.meta.url));
const { readAgentSession, formatAgentSession } = await import(pathToFileURL(join(checkout, 'packages/agent-core-v2/src/app/sessionExport/agent-session.ts')));
const scratch = mkdtempSync(join(tmpdir(), 'kimi-asr-native-'));
try {
  mkdirSync(join(scratch, 'agents/main'), { recursive: true });
  writeFileSync(join(scratch, 'agents/main/wire.jsonl'), readFileSync(join(directory, 'samples/native/native.jsonl')));
  const text = await readAgentSession(scratch, 'synthetic-kimi');
  if (process.argv.includes('--write')) writeFileSync(join(directory, 'samples/asr/session.jsonl'), text);
  else assert.equal(text, readFileSync(join(directory, 'samples/asr/session.jsonl'), 'utf8'));
  const rows = text.trimEnd().split('\n').map(line => JSON.parse(line));
  assert.equal(rows.find(row => row.role === 'user').id, 'prompt-1');
  const metadata = '{"type":"metadata","protocol_version":"1.5"}\n';
  const event = (type, values) => JSON.stringify({ type: 'context.append_loop_event', event: { type, ...values } }) + '\n';
  const edge = metadata + event('tool.call', { toolCallId: 'c', name: 'read' })
    + event('tool.result', { toolCallId: 'c', result: { output: 'old', isError: false } })
    + event('content.part', { part: { type: 'think', think: 'Exact\r\n', encrypted: 'SYNTHETIC-OPAQUE' } })
    + event('tool.result', { toolCallId: 'c', result: { output: 'new', isError: true } });
  const folded = formatAgentSession(edge, 'synthetic');
  const foldedRows = folded.trimEnd().split('\n').map(line => JSON.parse(line));
  assert.equal(foldedRows.filter(row => row.type === 'tool_result').length, 1);
  assert.equal(foldedRows.at(-1).status, 'failed');
  assert.ok(folded.includes('Exact\\r\\n'));
  assert.ok(!folded.includes('SYNTHETIC-OPAQUE'));
  assert.ok(formatAgentSession(edge + '{broken}\n', 'synthetic').includes('unparseable'));
  assert.ok(formatAgentSession(edge + '{partial', 'synthetic').includes('not_retained'));
  assert.throws(() => formatAgentSession('{"type":"metadata","protocol_version":"1.4"}\n', 'synthetic'), /Unsupported/);
  writeFileSync(join(scratch, 'session.asr.jsonl'), text);
  const validated = spawnSync(process.execPath, [resolve(directory, '../../tools/validator/bin/asr-validate.js'), '--summary', join(scratch, 'session.asr.jsonl')], { encoding: 'utf8' });
  assert.equal(validated.status, 0, validated.stdout + validated.stderr);
  process.stdout.write(validated.stdout);
  console.log('kimi-code: native journal, final results, partial lines, exact reasoning, and protocol checks passed');
} finally { rmSync(scratch, { recursive: true, force: true }); }
