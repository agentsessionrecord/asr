import { readFileSync, writeFileSync } from 'node:fs';
const source = new URL('../../../python/agent_session_record/src/agent_session_record/hook-conventions.json', import.meta.url);
const target = new URL('../src/hook-conventions.json', import.meta.url);
const expected = readFileSync(source, 'utf8');
if (process.argv.includes('--check')) {
  if (readFileSync(target, 'utf8') !== expected) throw new Error('Hook conventions need regeneration');
} else writeFileSync(target, expected);
