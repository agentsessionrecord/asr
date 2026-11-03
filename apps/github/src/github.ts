import { createHmac, createSign, timingSafeEqual } from 'node:crypto';
import { type PullRequest } from './report.js';
import { fullId } from './git.js';

export type TokenProvider = (installation: number) => Promise<string>;
export function apiBase(value: string): string {
  const url = new URL(value);
  if ((url.protocol !== 'https:' && !(url.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)))
    || url.username || url.password || url.search || url.hash) throw new Error('GitHub API must use HTTPS or loopback HTTP');
  return url.href.replace(/\/$/, '');
}
export function appJWT(appId: string, privateKey: string, now = Date.now()): string {
  if (!/^[0-9]+$/.test(appId)) throw new Error('App ID must be numeric');
  const encode = (data: object) => Buffer.from(JSON.stringify(data)).toString('base64url');
  const body = `${encode({ alg: 'RS256', typ: 'JWT' })}.${encode({ iat: Math.floor(now / 1000) - 60, exp: Math.floor(now / 1000) + 540, iss: appId })}`;
  return `${body}.${createSign('RSA-SHA256').update(body).sign(privateKey, 'base64url')}`;
}
export function validSignature(raw: Uint8Array, signature: string | undefined, secret: string): boolean {
  if (!secret || !signature || !/^sha256=[a-f0-9]{64}$/.test(signature)) return false;
  const expected = createHmac('sha256', secret).update(raw).digest();
  return timingSafeEqual(expected, Buffer.from(signature.slice(7), 'hex'));
}
async function request(base: string, route: string, token: string, method = 'GET', body?: object): Promise<any> {
  const response = await fetch(base + route, { method, redirect: 'error', signal: AbortSignal.timeout(30_000),
    headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'asr-github-app', ...(body ? { 'Content-Type': 'application/json' } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}) });
  if (!response.ok) throw new Error(`GitHub API ${method} returned ${response.status}`);
  // Never include response bodies in errors. They may contain private content.
  const reader = response.body?.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  if (reader) for (;;) {
    const next = await reader.read();
    if (next.done) break;
    size += next.value.length;
    if (size > 16 * 1024 * 1024) { await reader.cancel(); throw new Error('GitHub response exceeds size limit'); }
    chunks.push(next.value);
  }
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { throw new Error('Invalid GitHub API JSON response'); }
}
export function installationTokens(base: string, appId: string, key: string): TokenProvider {
  base = apiBase(base);
  const cache = new Map<number, { token: string; expires: number }>();
  return async installation => {
    if (!Number.isSafeInteger(installation) || installation < 1) throw new Error('Invalid installation');
    const found = cache.get(installation);
    if (found && found.expires > Date.now() + 60_000) return found.token;
    const result = await request(base, `/app/installations/${installation}/access_tokens`, appJWT(appId, key), 'POST', {});
    if (typeof result.token !== 'string' || !Number.isFinite(Date.parse(result.expires_at))) throw new Error('Invalid installation token response');
    cache.set(installation, { token: result.token, expires: Date.parse(result.expires_at) });
    return result.token;
  };
}
export function repoRoute(repository: string): string {
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository) || repository.split('/').some(v => v === '.' || v === '..')) throw new Error('Invalid repository name');
  return `/repos/${repository}`;
}
export class GitHub {
  readonly base: string;
  constructor(base: string, readonly tokens: TokenProvider, readonly appId: number) {
    this.base = apiBase(base);
    if (!Number.isSafeInteger(appId) || appId < 1) throw new Error('Invalid App ID');
  }
  async call(installation: number, route: string, method = 'GET', body?: object): Promise<any> {
    return request(this.base, route, await this.tokens(installation), method, body);
  }
  async pages(installation: number, route: string): Promise<any[]> {
    const result: any[] = [];
    for (let page = 1; page <= 100; page++) {
      const data = await this.call(installation, `${route}${route.includes('?') ? '&' : '?'}per_page=100&page=${page}`);
      if (!Array.isArray(data)) throw new Error('Invalid paginated GitHub response');
      result.push(...data);
      if (data.length < 100) return result;
    }
    throw new Error('GitHub pagination limit exceeded');
  }
  async pullRequest(installation: number, repository: string, number: number): Promise<PullRequest> {
    if (!Number.isSafeInteger(number) || number < 1) throw new Error('Invalid pull request number');
    const route = `${repoRoute(repository)}/pulls/${number}`;
    const pull = await this.call(installation, route);
    if (!fullId(pull.head?.sha)) throw new Error('Invalid pull request head');
    const commits = await this.pages(installation, `${route}/commits`);
    // The GitHub endpoint returns at most 250 commits. Fail closed at that boundary.
    if (commits.length >= 250 || commits.some(c => !fullId(c.sha))) throw new Error('Incomplete or invalid pull request commit list');
    const confirm = await this.call(installation, route);
    if (confirm.head?.sha !== pull.head.sha || confirm.merged !== pull.merged || confirm.merge_commit_sha !== pull.merge_commit_sha) throw new Error('Pull request changed during lookup');
    return { repository, number, head: pull.head.sha, commits: commits.map(c => c.sha), merged: pull.merged === true,
      mergeCommit: pull.merged === true && fullId(pull.merge_commit_sha) ? pull.merge_commit_sha : undefined };
  }
  async publish(installation: number, pr: PullRequest, summary: string, mode: 'check' | 'comment'): Promise<void> {
    const root = repoRoute(pr.repository), current = await this.call(installation, `${root}/pulls/${pr.number}`);
    if (current.head?.sha !== pr.head || current.merged !== (pr.merged === true)
      || (pr.merged && fullId(current.merge_commit_sha) && current.merge_commit_sha !== pr.mergeCommit)) throw new Error('Pull request changed before publication');
    if (mode === 'check') {
      const found = (await this.call(installation, `${root}/commits/${pr.head}/check-runs?check_name=ASR%20sessions&filter=latest&per_page=100`)).check_runs;
      if (!Array.isArray(found)) throw new Error('Invalid check run response');
      const external = `asr:${pr.repository}:${pr.number}`;
      const existing = found.find(c => c.external_id === external && c.app?.id === this.appId && Number.isSafeInteger(c.id));
      const body = { name: 'ASR sessions', head_sha: pr.head, external_id: external, status: 'completed', conclusion: 'neutral',
        output: { title: 'Sessions behind this pull request', summary } };
      const { head_sha, ...update } = body;
      await this.call(installation, existing ? `${root}/check-runs/${existing.id}` : `${root}/check-runs`, existing ? 'PATCH' : 'POST', existing ? update : body);
    } else {
      // A user marker or another app's bot cannot select a comment to edit.
      const comments = await this.pages(installation, `${root}/issues/${pr.number}/comments`);
      const existing = comments.find(c => c.user?.type === 'Bot' && c.performed_via_github_app?.id === this.appId
        && typeof c.body === 'string' && c.body.startsWith('<!-- asr-github-summary -->') && Number.isSafeInteger(c.id));
      await this.call(installation, existing ? `${root}/issues/comments/${existing.id}` : `${root}/issues/${pr.number}/comments`, existing ? 'PATCH' : 'POST', { body: summary });
    }
  }
}
