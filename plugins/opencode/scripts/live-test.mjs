import { mkdtempSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';

// This opt-in check uses an installed CLI and an OpenAI-compatible endpoint.
const [agent, binary, destination] = process.argv.slice(2);
const entries = { opencode: ['index', 'OPENCODE'], kilo: ['kilo', 'KILO'], mimocode: ['mimocode', 'MIMOCODE'] };
const model = process.env.ASR_OPENAI_MODEL;
const endpoint = process.env.ASR_OPENAI_BASE_URL;
const keyFile = process.env.ASR_PROVIDER_KEY_FILE;
if (!entries[agent] || !binary || !keyFile || !model || !endpoint) {
  throw new Error('Set ASR_OPENAI_MODEL, ASR_OPENAI_BASE_URL and ASR_PROVIDER_KEY_FILE, then run live-test.mjs AGENT CLI_PATH [SUMMARY_PATH]');
}
const route = new URL(endpoint);
if (!['http:', 'https:'].includes(route.protocol) || route.hostname !== '127.0.0.1' || (!route.port && !/^https?:\/\/127\.0\.0\.1:(?:80|443)(?:\/|$)/.test(endpoint)) || route.port === '0'
  || route.username || route.password || route.search || route.hash) throw new Error('explicit_loopback_endpoint_required');
const pluginRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const root = resolve(pluginRoot, '../..');
const scratch = mkdtempSync(join(tmpdir(), 'asr-family-live-'));
try {
  for (const directory of ['home', 'config', 'data', 'cache', 'state', 'work', 'asr']) mkdirSync(join(scratch, directory), { mode: 0o700 });
  const [entry, prefix] = entries[agent];
  const helper = join(scratch, 'rewrite.js');
  writeFileSync(helper, 'export default async () => ({"tool.execute.before": async (input, output) => { if (input.tool === "bash" && output.args.command === "printf ASR_REQUEST") output.args.command = "printf ASR_REWRITTEN"; }});\n');
  const config = {
    model: `asr_test/${model}`, small_model: `asr_test/${model}`,
    plugin: [pathToFileURL(join(pluginRoot, 'dist', `${entry}.js`)).href, pathToFileURL(helper).href],
    provider: { asr_test: { name: 'Synthetic test endpoint', npm: '@ai-sdk/openai-compatible', options: { baseURL: endpoint, apiKey: readFileSync(keyFile, 'utf8').trim() }, models: { [model]: { name: 'Synthetic model', limit: { context: 200000, output: 4096 } } } } },
    permission: { '*': 'deny', bash: { '*': 'allow', 'printf ASR_DENIED': 'deny' } },
  };
  const settings = join(scratch, 'config/provider.json');
  writeFileSync(settings, JSON.stringify(config), { mode: 0o600, flag: 'wx' });
  const loaded = JSON.parse(readFileSync(settings, 'utf8'));
  if (loaded.model !== `asr_test/${model}` || loaded.provider.asr_test.options.baseURL !== endpoint) throw new Error('provider_settings_mismatch');
  const env = {
    PATH: process.env.PATH, HOME: join(scratch, 'home'), XDG_CONFIG_HOME: join(scratch, 'config'), XDG_DATA_HOME: join(scratch, 'data'), XDG_CACHE_HOME: join(scratch, 'cache'), XDG_STATE_HOME: join(scratch, 'state'),
    ASR_OUTPUT_DIR: join(scratch, 'asr'), ASR_CONTENT: 'full',
    CI: '1', NO_COLOR: '1', DO_NOT_TRACK: '1', KILO_DISABLE_TELEMETRY: 'true', KILO_DISABLE_SESSION_INGEST: 'true', MIMOCODE_ENABLE_ANALYSIS: 'false', MIMOCODE_HOME: join(scratch, 'home'),
    [prefix + '_CONFIG']: settings,
  };
  for (const name of ['OPENCODE', 'KILO', 'MIMOCODE']) {
    for (const flag of ['DISABLE_AUTOUPDATE', 'DISABLE_MODELS_FETCH', 'DISABLE_DEFAULT_PLUGINS', 'DISABLE_CLAUDE_CODE', 'DISABLE_EXTERNAL_SKILLS', 'DISABLE_LSP_DOWNLOAD', 'DISABLE_INSTRUCTIONS', 'DISABLE_BUILTIN_SKILLS', 'DISABLE_OFFICIAL_SKILLS', 'DISABLE_CHECKPOINT', 'DISABLE_CRON']) env[`${name}_${flag}`] = 'true';
  }
  const prompt = agent === 'mimocode'
    ? 'Run the bash command printf ASR_LIVE_OK exactly once, then reply DONE. Do not read files, start subagents, or use other tools.'
    : 'Use bash for two separate commands in order. First run exactly printf ASR_REQUEST. Second run exactly printf ASR_DENIED. The second command is configured to be denied. Do not combine commands or retry a refusal. Then reply DONE. Do not read files, start subagents, or use other tools.';
  const run = spawnSync(resolve(binary), ['run', '--format', 'json', '--model', `asr_test/${model}`, '--title', 'Synthetic recorder test', prompt], { cwd: join(scratch, 'work'), env, input: '', encoding: 'utf8', timeout: 120000, killSignal: 'SIGKILL', maxBuffer: 4 * 1024 * 1024 });
  const paths = readdirSync(join(scratch, 'asr')).filter(file => file.endsWith('.jsonl')).map(file => join(scratch, 'asr', file));
  const records = paths.flatMap(path => readFileSync(path, 'utf8').trimEnd().split('\n').map(JSON.parse));
  const results = records.filter(record => record.type === 'tool_result');
  const validations = paths.map(path => {
    const validation = spawnSync(process.execPath, [join(root, 'tools/validator/bin/asr-validate.js'), '--json', path], { encoding: 'utf8' });
    return JSON.parse(validation.stdout);
  });
  const rewritten = results.filter(record => record.input?.command === 'printf ASR_REWRITTEN' && record.content?.some(part => part.text?.includes('ASR_REWRITTEN'))).length;
  const denied = results.filter(record => record.input?.command === 'printf ASR_DENIED' && record.status === 'failed').length;
  const observedMarker = results.filter(record => record.content?.some(part => part.text?.includes('ASR_LIVE_OK'))).length;
  const summary = {
    agent, exit: run.status, streams: paths.length, records: records.length,
    calls: records.filter(record => record.type === 'tool_call').length, results: results.length,
    scenario: agent === 'mimocode' ? 'wrapper-command' : 'rewrite-refusal',
    rewritten, denied, observedMarker, validationErrors: validations.reduce((total, validation) => total + validation.errors, 0),
    warningCodes: Object.fromEntries(validations.flatMap(validation => Object.entries(validation.counts)).reduce((counts, [code, count]) => counts.set(code, (counts.get(code) ?? 0) + count), new Map())),
  };
  if (destination) writeFileSync(resolve(destination), JSON.stringify(summary, null, 2) + '\n');
  console.log(JSON.stringify(summary));
  const exercised = agent === 'mimocode' ? observedMarker > 0 : rewritten > 0 && denied > 0;
  if (run.status !== 0 || !paths.length || !exercised || summary.validationErrors) process.exitCode = 1;
} finally {
  rmSync(scratch, { recursive: true, force: true });
}
