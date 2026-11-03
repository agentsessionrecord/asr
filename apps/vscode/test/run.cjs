const path = require('node:path');
const fs = require('node:fs/promises');
const os = require('node:os');
const { runTests, downloadAndUnzipVSCode } = require('@vscode/test-electron');
(async () => {
  const scratch = await fs.mkdtemp(path.join(os.tmpdir(), 'asr-vscode-harness-'));
  try {
    const { fixture } = await import('./fixture.mjs');
    const data = await fixture(scratch);
    await fs.mkdir(path.join(scratch, 'user', 'User'), { recursive: true });
    const cli = process.env.ASR_EDITOR_CLI || path.resolve(__dirname, '../../../target/debug/asr');
    await fs.writeFile(path.join(scratch, 'user', 'User', 'settings.json'), JSON.stringify({ 'asr.executable': cli, 'asr.sessions': [data.store], 'asr.annotations': [], 'security.workspace.trust.enabled': false, 'extensions.autoUpdate': false, 'update.mode': 'none', 'telemetry.telemetryLevel': 'off' }));
    const cachePath = path.resolve(__dirname, '../../../node_modules/.cache/asr-vscode');
    await fs.mkdir(cachePath, { recursive: true });
    const vscodeExecutablePath = await downloadAndUnzipVSCode({ version: '1.109.0', cachePath });
    await runTests({ vscodeExecutablePath, extensionDevelopmentPath: path.resolve(__dirname, '..'), extensionTestsPath: path.join(__dirname, 'suite', 'index.cjs'), launchArgs: [data.repo, '--user-data-dir', path.join(scratch, 'user'), '--extensions-dir', path.join(scratch, 'extensions'), '--disable-workspace-trust', '--disable-gpu', '--no-sandbox', '--skip-welcome', '--skip-release-notes'], extensionTestsEnv: { ASR_EDITOR_FIXTURE: path.join(scratch, 'fixture.json') } });
  } finally { await fs.rm(scratch, { recursive: true, force: true }); }
})().catch(error => { console.error(error); process.exitCode = 1; });
