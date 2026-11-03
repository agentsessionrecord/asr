import { readFileSync, writeFileSync } from 'node:fs';
import { exportTranscript } from './plugin/transcript.mjs';
const events = JSON.parse(readFileSync(new URL('./samples/native/plugin-projection.json', import.meta.url), 'utf8'));
const stream = exportTranscript('synthetic-plugin', events);
if (process.argv[2]) writeFileSync(process.argv[2], stream, { mode: 0o600, flag: 'wx' });
else process.stdout.write(stream);
