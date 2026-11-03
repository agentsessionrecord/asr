import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

// Run from a patched OpenClaw checkout with its source loader.
const [input, output] = process.argv.slice(2);
if (!input || !output) throw new Error('Provide native source and ASR output paths.');
const owner = await import(pathToFileURL(path.resolve('src/sessions/agent-session-export.ts')));
const json = await import(pathToFileURL(path.resolve('src/sessions/agent-session-export.json.ts')));
const snapshot = json.parseObject(readFileSync(input, 'utf8'));
const source = { ...snapshot, inputRuns: new Map(snapshot.inputRuns), runOwners: new Map(snapshot.runOwners) };
const result = owner.convertAgentSession(source);
writeFileSync(output, result.records.map((record) => JSON.stringify(record)).join('\n') + '\n', { mode: 0o600, flag: 'wx' });
console.log(JSON.stringify({ records: result.records.length }));
