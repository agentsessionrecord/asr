import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const checkout = resolve(process.argv[2]);
const require = createRequire(resolve(checkout, 'package.json'));
const { createJiti } = require('jiti');
const { Command } = require('commander');
const jiti = createJiti(import.meta.url, { alias: {
  'openclaw/plugin-sdk/plugin-entry': resolve(checkout, 'src/plugin-sdk/plugin-entry.ts'),
  'openclaw/plugin-sdk/session-transcript-runtime': resolve(checkout, 'src/plugin-sdk/session-transcript-runtime.ts'),
} });
const plugin = await jiti.import(fileURLToPath(new URL('./index.ts', import.meta.url)), { default: true });
assert.equal(plugin.id, 'asr-export');
let registration;
let metadata;
plugin.register({ registerCli(callback, options) { registration = callback; metadata = options; } });
assert.equal(metadata.descriptors[0].name, 'asr-export');
const program = new Command();
await registration({ program });
const command = program.commands.find(command => command.name() === 'asr-export');
assert.ok(command);
assert.deepEqual(command.options.map(option => option.long), ['--agent', '--session-key', '--session', '--output']);
console.log('OpenClaw public SDK entry and CLI registration passed.');
