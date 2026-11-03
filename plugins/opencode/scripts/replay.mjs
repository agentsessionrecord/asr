import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { Recorder } from '../dist/recorder.js';

if (!process.argv[2]) throw new Error('Supply a new output directory');
const trace = JSON.parse(readFileSync(new URL('../test/fixtures/legacy.json', import.meta.url)));
for (const agent of ['opencode', 'kilo', 'mimocode']) {
  let tick = 0;
  const recorder = new Recorder({ agent, directory: resolve(process.argv[2]), content: 'full', secrets: [], now: () => new Date(1793534400000 + tick++).toISOString() });
  for (const item of trace) recorder.observe(item.name, item.input, item.output);
  recorder.close();
}
