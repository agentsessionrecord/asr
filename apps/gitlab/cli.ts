import { readFileSync } from 'node:fs';
import { Git, fullId } from '../../exporters/git-notes/src/git.ts';
import { loadStore } from '../../exporters/git-notes/src/reader.ts';
import { buildReport, GitLabApi, renderSummary } from './src/index.ts';

try {
  const [configFile, mode = '--offline', ...commits] = process.argv.slice(2);
  if (!configFile || !['--offline', '--dry-run', '--post'].includes(mode))
    throw new Error('Usage: cli.ts CONFIG.json [--offline COMMIT... | --dry-run | --post]');
  const config = JSON.parse(readFileSync(configFile, 'utf8')), git = new Git(config.repo), store = loadStore(config.store);
  let api: GitLabApi | undefined;
  let members: string[];
  if (mode === '--offline') {
    if (!commits.length) throw new Error('Offline mode needs at least one commit.');
    members = commits.map(id => git.resolve(id));
  } else {
    const token = process.env.ASR_GITLAB_TOKEN;
    if (!token) throw new Error('Set ASR_GITLAB_TOKEN for GitLab API access.');
    api = new GitLabApi(config.apiBase, token);
    members = await api.commits(git, config.project, config.mergeRequest);
  }
  if (!members.every(fullId)) throw new Error('Full commit IDs are required.');
  const report = buildReport(git, members, store, config.repositories), body = renderSummary(report, config.sessionBaseUrl);
  if (mode === '--post') console.log(JSON.stringify(await api!.postSummary(config.project, config.mergeRequest, body)));
  else console.log(body);
} catch (error) {
  console.error(error instanceof Error ? error.message : 'GitLab integration failed.'); process.exitCode = 1;
}
