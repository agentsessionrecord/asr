import { readFile, writeFile } from 'node:fs/promises';
import { App, readConfig, webhookServer } from './app.js';
import { GitHub, installationTokens } from './github.js';

async function main(): Promise<void> {
  const [command, configFile, repository, number, output] = process.argv.slice(2);
  if (!['report', 'serve'].includes(command) || !configFile || (command === 'report' && (!repository || !number || !output))
    || (command === 'serve' && repository !== undefined)) throw new Error('Usage: node dist/cli.js report CONFIG OWNER/REPO PR OUTPUT.json | serve CONFIG');
  const config = await readConfig(configFile);
  const appId = process.env.ASR_GITHUB_APP_ID, keyFile = process.env.ASR_GITHUB_PRIVATE_KEY_FILE;
  if (!appId || !keyFile) throw new Error('ASR_GITHUB_APP_ID and ASR_GITHUB_PRIVATE_KEY_FILE are required');
  const github = new GitHub(config.apiUrl, installationTokens(config.apiUrl, appId, await readFile(keyFile, 'utf8')), Number(appId));
  const app = new App(config, github);
  if (command === 'report') {
    const result = await app.report(repository, Number(number));
    await writeFile(output, JSON.stringify(result.report, null, 2) + '\n', { mode: 0o600, flag: 'wx' });
    await writeFile(output + '.md', result.summary + '\n', { mode: 0o600, flag: 'wx' });
    console.log(`Report written. ${result.report.sessions.length} candidate sessions.`);
  } else {
    const secret = process.env.ASR_GITHUB_WEBHOOK_SECRET;
    if (!secret) throw new Error('ASR_GITHUB_WEBHOOK_SECRET is required');
    const port = Number(process.env.ASR_GITHUB_PORT ?? '8787');
    if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid port');
    const server = webhookServer(app, secret);
    await new Promise<void>((resolve, reject) => {
      server.once('error', reject);
      server.listen(port, '127.0.0.1', resolve);
    });
    console.log(`Webhook listener on 127.0.0.1:${port}`);
    const stop = () => { server.close(); server.closeAllConnections(); };
    process.once('SIGTERM', stop);
    process.once('SIGINT', stop);
  }
}
main().catch(() => { console.error('GitHub app failed. Check configuration, credentials, local objects and API availability. No credentials or response content are logged.'); process.exitCode = 1; });
