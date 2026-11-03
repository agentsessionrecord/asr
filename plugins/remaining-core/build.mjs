import { build } from 'esbuild';
import { cpSync, mkdirSync, readFileSync, writeFileSync, existsSync, readdirSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { events, kimiV2Events } from './configure.mjs';

export const agents = ['goose', 'pi', 'cline', 'kimi-code', 'grok-build', 'deepseek-harness', 'crush', 'mux', 'amp'];
const root = fileURLToPath(new URL('../../', import.meta.url));
const quote = value => "'" + value.replaceAll("'", "'\\''") + "'";

/** Build a local install directory with no imports back into this checkout. */
export async function buildPlugin(agent, target) {
  if (!agents.includes(agent)) throw new Error('Unknown recorder');
  target = resolve(target);
  if (existsSync(target) && readdirSync(target).length) throw new Error('Build target must be empty');
  mkdirSync(target, { recursive: true, mode: 0o700 });
  const directory = join(root, 'plugins', agent);
  const entry = ['pi', 'amp'].includes(agent) ? join(directory, 'index.mjs') : agent === 'mux' ? join(directory, 'server.mjs') : join(root, 'plugins/remaining-core/command.mjs');
  const filename = ['pi', 'amp'].includes(agent) ? 'index.mjs' : agent === 'mux' ? 'server.mjs' : 'command.mjs';
  await build({ entryPoints: [entry], outfile: join(target, filename), bundle: true, format: 'esm',
    platform: 'node', target: 'node22', absWorkingDir: root, logLevel: 'silent',
    // Ajv's CommonJS dependencies use require at runtime.
    banner: { js: "import { createRequire as asrCreateRequire } from 'node:module'; const require = asrCreateRequire(import.meta.url);" } });
  if (agent === 'cline') await build({ entryPoints: [join(directory, 'tail-audit.mjs')], outfile: join(target, 'tail-audit.mjs'),
    bundle: true, format: 'esm', platform: 'node', target: 'node22', absWorkingDir: root, logLevel: 'silent',
    banner: { js: "import { createRequire as asrCreateRequire } from 'node:module'; const require = asrCreateRequire(import.meta.url);" } });
  for (const name of ['README.md', 'sources.json']) if (existsSync(join(directory, name))) cpSync(join(directory, name), join(target, name));
  const command = `node ${quote(join(target, filename))} ${agent}`;
  const commandHooks = names => ({ hooks: Object.fromEntries(names.map(name => [name,
    [{ hooks: [{ type: 'command', command, timeout: 1 }] }]])) });
  if (agent === 'goose') {
    cpSync(join(directory, 'plugin.json'), join(target, 'plugin.json'));
    mkdirSync(join(target, 'hooks'));
    const config = commandHooks(events.goose);
    for (const groups of Object.values(config.hooks)) groups[0].hooks[0].command = 'node "${PLUGIN_ROOT}/command.mjs" goose';
    writeFileSync(join(target, 'hooks/hooks.json'), JSON.stringify(config, null, 2) + '\n');
  } else if (agent === 'mux') {
    for (const name of ['.codex-plugin', '.mcp.json', 'hooks']) cpSync(join(directory, name), join(target, name), { recursive: true });
  } else if (agent === 'cline') {
    cpSync(join(directory, 'hooks'), join(target, 'hooks'), { recursive: true });
    for (const name of readdirSync(join(target, 'hooks'))) {
      const path = join(target, 'hooks', name);
      writeFileSync(path, readFileSync(path, 'utf8').replace('"$hook_dir/../../remaining-core/command.mjs"', quote(join(target, 'command.mjs'))));
    }
  } else if (agent === 'kimi-code') {
    for (const [filename, names] of [['hooks.toml', events[agent]], ['hooks-v2.toml', kimiV2Events]]) {
      writeFileSync(join(target, filename), names.map(event =>
        `[[hooks]]\nevent = ${JSON.stringify(event)}\ncommand = ${JSON.stringify(command)}\ntimeout = 1\n`).join('\n'));
    }
  } else if (agent === 'crush') {
    writeFileSync(join(target, 'hooks.json'), JSON.stringify({ hooks: Object.fromEntries(events.crush.map(event =>
      [event, [{ name: 'asr-recorder', command, timeout: 1 }]])) }, null, 2) + '\n');
  } else if (agent === 'pi') {
    writeFileSync(join(target, 'package.json'), JSON.stringify({ name: 'asr-pi-recorder', version: '0.1.0', type: 'module', pi: { extensions: ['./index.mjs'] } }, null, 2) + '\n');
  } else if (agent !== 'amp') writeFileSync(join(target, 'hooks.json'), JSON.stringify(commandHooks(events[agent]), null, 2) + '\n');
  return target;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [agent, output] = process.argv.slice(2);
  if (!output) throw new Error('Usage: node plugins/remaining-core/build.mjs AGENT EMPTY_OUTPUT_DIRECTORY');
  await buildPlugin(agent, output);
}
