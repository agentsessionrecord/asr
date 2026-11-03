import { readFileSync, writeFileSync, mkdtempSync, rmSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { agents } from '../build.mjs';
import { adapt } from '../adapters.mjs';
import { parse, record } from '../recorder.mjs';
import piPlugin from '../../pi/index.mjs';
import ampPlugin from '../../amp/index.mjs';

const timestamp = '2026-11-01T00:00:00.000Z';
let streams = 0, records = 0, warnings = {};
for (const { agent, variant = '' } of [...agents.map(agent => ({ agent })), { agent: 'kimi-code', variant: '-v2' }]) {
  const directory = mkdtempSync(join(tmpdir(), 'asr-samples-'));
  const filename = new URL(`../../${agent}/fixtures/recorded${variant}.asr.jsonl`, import.meta.url);
  const observations = readFileSync(new URL(`../../${agent}/fixtures/native${variant}.jsonl`, import.meta.url), 'utf8').trimEnd().split('\n').map(parse);
  const previous = { date: globalThis.Date, output: process.env.ASR_OUTPUT_DIR, content: process.env.ASR_CONTENT };
  try {
    if (['pi', 'amp'].includes(agent)) {
      globalThis.Date = class extends previous.date { constructor(...args) { super(...(args.length ? args : [timestamp])); } };
      process.env.ASR_OUTPUT_DIR = directory; process.env.ASR_CONTENT = 'full';
      const handlers = new Map();
      await (agent === 'pi' ? piPlugin : ampPlugin)({ on: (name, handler) => handlers.set(name, handler) });
      for (const event of observations) await handlers.get(event.type || event.event)(event,
        { cwd: '/work/synthetic', sessionManager: { getSessionId: () => 'synthetic-session' } });
    } else for (const payload of observations) {
      if (!record(agent, adapt(agent, payload), { env: { ASR_OUTPUT_DIR: directory, ASR_CONTENT: 'full' }, now: timestamp })) throw new Error(`${agent}: capture failed`);
    }
    const path = join(directory, readdirSync(directory).find(name => name.endsWith('.jsonl')));
    const actual = readFileSync(path, 'utf8');
    if (process.argv.includes('--write')) writeFileSync(filename, actual);
    else if (actual !== readFileSync(filename, 'utf8')) throw new Error(`${agent}: sample drift`);
    const validation = spawnSync(process.execPath, ['tools/validator/bin/asr-validate.js', '--json', path], { encoding: 'utf8' });
    const report = JSON.parse(validation.stdout);
    if (validation.status !== 0 || report.errors) throw new Error(`${agent}: sample validation failed`);
    streams++; records += report.records;
    for (const [code, count] of Object.entries(report.counts)) warnings[code] = (warnings[code] || 0) + count;
  } finally {
    globalThis.Date = previous.date;
    for (const [key, value] of [['ASR_OUTPUT_DIR', previous.output], ['ASR_CONTENT', previous.content]]) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
    rmSync(directory, { recursive: true, force: true });
  }
}
console.log(JSON.stringify({ streams, records, errors: 0, warnings }));
