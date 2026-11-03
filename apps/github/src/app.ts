import { createServer, type Server } from 'node:http';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { Git } from './git.js';
import { GitHub, validSignature, repoRoute, apiBase } from './github.js';
import { loadStore } from './store.js';
import { buildReport, renderSummary, sessionURL, type Report } from './report.js';

export interface Config {
  store: string;
  sessionsBaseUrl: string;
  apiUrl: string;
  mode: 'check' | 'comment';
  repositories: { name: string; installation: number; path: string; recordedRoots: string[] }[];
}
export async function readConfig(file: string): Promise<Config> {
  const data = JSON.parse(await readFile(file, 'utf8'));
  if (typeof data.store !== 'string' || typeof data.sessionsBaseUrl !== 'string' || !Array.isArray(data.repositories)
    || !['check', 'comment'].includes(data.mode ?? 'check')) throw new Error('Invalid configuration');
  sessionURL(data.sessionsBaseUrl, 'com.example.agent:test');
  const seen = new Set<string>(), base = path.dirname(path.resolve(file));
  for (const repo of data.repositories) {
    repoRoute(repo.name);
    if (seen.has(repo.name) || typeof repo.path !== 'string' || !Number.isSafeInteger(repo.installation) || repo.installation < 1
      || (repo.recordedRoots !== undefined && (!Array.isArray(repo.recordedRoots) || repo.recordedRoots.some((p: unknown) => typeof p !== 'string' || !path.posix.isAbsolute(p))))) throw new Error('Invalid repository configuration');
    seen.add(repo.name);
    repo.path = path.resolve(base, repo.path);
    repo.recordedRoots ??= [];
  }
  return { ...data, store: path.resolve(base, data.store), apiUrl: apiBase(data.apiUrl ?? 'https://api.github.com'), mode: data.mode ?? 'check' };
}
export class App {
  private queue = new Map<string, Promise<unknown>>();
  private delivered = new Map<string, number>();
  constructor(readonly config: Config, readonly github: GitHub) {}
  async report(repository: string, number: number): Promise<{ report: Report; summary: string; pull: Awaited<ReturnType<GitHub['pullRequest']>> }> {
    const repo = this.config.repositories.find(r => r.name === repository);
    if (!repo) throw new Error('Repository is not configured');
    const pull = await this.github.pullRequest(repo.installation, repository, number);
    const store = await loadStore(this.config.store);
    const report = buildReport(new Git(repo.path, repo.recordedRoots), store, pull);
    return { report, summary: renderSummary(report, this.config.sessionsBaseUrl), pull };
  }
  async webhook(raw: Buffer, event: string, signature: string | undefined, secret: string, delivery: string): Promise<'published' | 'ignored'> {
    if (!validSignature(raw, signature, secret)) throw new Error('Invalid webhook signature');
    if (!/^[A-Za-z0-9-]{1,128}$/.test(delivery)) throw new Error('Invalid webhook delivery ID');
    if (event !== 'pull_request') return 'ignored';
    let body: any;
    try { body = JSON.parse(raw.toString('utf8')); } catch { throw new Error('Invalid webhook JSON'); }
    if (!['opened', 'reopened', 'synchronize', 'ready_for_review', 'closed'].includes(body.action)) return 'ignored';
    const repository = body.repository?.full_name, number = body.number;
    const repo = this.config.repositories.find(r => r.name === repository && r.installation === body.installation?.id);
    if (!repo || !Number.isSafeInteger(number) || number < 1) return 'ignored';
    const now = Date.now();
    for (const [id, at] of this.delivered) if (at < now - 86_400_000) this.delivered.delete(id);
    if (this.delivered.has(delivery)) return 'ignored';
    const key = `${repository}#${number}`;
    const previous = this.queue.get(key) ?? Promise.resolve();
    const next = previous.catch(() => {}).then(async () => {
      if (this.delivered.has(delivery)) return 'ignored' as const;
      const { pull, summary } = await this.report(repository, number);
      await this.github.publish(repo.installation, pull, summary, this.config.mode);
      this.delivered.set(delivery, Date.now());
      if (this.delivered.size > 10_000) this.delivered.delete(this.delivered.keys().next().value!);
      return 'published' as const;
    });
    this.queue.set(key, next);
    try { return await next; } finally { if (this.queue.get(key) === next) this.queue.delete(key); }
  }
}
export function webhookServer(app: App, secret: string): Server {
  if (!secret) throw new Error('Webhook secret is required');
  return createServer(async (req, res) => {
    if (req.method !== 'POST' || req.url !== '/webhook') { res.writeHead(404).end(); return; }
    const chunks: Buffer[] = [];
    let size = 0;
    try {
      for await (const chunk of req) {
        size += chunk.length;
        if (size > 2 * 1024 * 1024) { res.writeHead(413).end('Payload too large'); return; }
        chunks.push(chunk);
      }
      const header = (name: string): string | undefined => typeof req.headers[name] === 'string' ? req.headers[name] : undefined;
      const raw = Buffer.concat(chunks), signature = header('x-hub-signature-256');
      if (!validSignature(raw, signature, secret)) { res.writeHead(401).end('Invalid signature'); return; }
      const result = await app.webhook(raw, header('x-github-event') ?? '', signature, secret, header('x-github-delivery') ?? '');
      res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ result }));
    } catch {
      res.writeHead(500).end('Webhook processing failed');
    }
  });
}
