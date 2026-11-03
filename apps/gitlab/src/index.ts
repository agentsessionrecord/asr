import { Git, fullId } from '../../../exporters/git-notes/src/git.ts';
import type { RepoMap } from '../../../exporters/git-notes/src/git.ts';
import { analyzeCommit } from '../../../exporters/git-notes/src/attribution.ts';
import type { Analysis } from '../../../exporters/git-notes/src/attribution.ts';
import { authorshipCandidates, parseAuthorship } from '../../../exporters/git-notes/src/git-ai.ts';
import { linkRef, parseLinks, sessionUrl, trailers } from '../../../exporters/git-notes/src/notes.ts';
import { sessionSummary } from '../../../exporters/git-notes/src/reader.ts';
import type { Diagnostic, RecordData, Session } from '../../../exporters/git-notes/src/reader.ts';

export const marker = '<!-- agent-session-record:gitlab:v1 -->';
export type Store = { sessions: Session[]; annotations: RecordData[]; diagnostics: Diagnostic[] };
export type Report = ReturnType<typeof buildReport>;
export function buildReport(git: Git, commits: string[], store: Store, maps: RepoMap = []) {
  const analyses: Analysis[] = [], candidates = new Map<string, Set<string>>(), diagnostics = [...store.diagnostics];
  const add = (ref: string, reason: string) => {
    const key = ref.split('#')[0], reasons = candidates.get(key) ?? new Set<string>();
    reasons.add(reason); candidates.set(key, reasons);
  };
  for (const commit of [...new Set(commits)]) {
    if (!git.exists(commit)) { diagnostics.push({ code: 'commit-unavailable' }); continue; }
    const analysis = analyzeCommit(git, commit, store.sessions, maps, store.annotations);
    analyses.push(analysis);
    for (const c of analysis.committedBy) add(c.session, 'verified-commit');
    for (const l of analysis.lines) {
      if (l.editedBy) add(l.editedBy.session, 'surviving-edit');
      if (l.untracked) add(l.untracked.session, 'untracked-external-change');
      for (const e of l.competing ?? []) add(e.session, 'competing-edit');
    }
    for (const ref of trailers(git.run(['show', '-s', '--no-notes', '--format=%B', commit]))) add(ref, 'trailer-link');
    const links = git.note(commit, linkRef);
    if (links !== undefined) {
      try { for (const link of parseLinks(links).sessions) add(link.session, 'note-link'); }
      catch { diagnostics.push({ code: 'invalid-link-note' }); }
    }
    const ai = git.note(commit, 'refs/notes/ai');
    if (ai !== undefined) {
      try {
        for (const entry of authorshipCandidates(parseAuthorship(ai), store.sessions)) {
          for (const ref of entry.candidates) add(ref, `git-ai-${entry.status}`);
          if (entry.status === 'unresolved' || entry.status === 'ambiguous') diagnostics.push({ code: `git-ai-${entry.status}` });
        }
      } catch { diagnostics.push({ code: 'invalid-git-ai-note' }); }
    }
    // An annotation and a PR reference can locate a session, but supply no credit.
    for (const s of store.sessions) for (const r of s.records) if (r.type === 'vcs'
        && [r.commit, r.pr?.mergeCommit, ...(r.pr?.commits ?? [])].includes(commit)) add(s.ref, 'record-link');
    for (const a of store.annotations) if ([a.data?.commit, a.data?.pr?.mergeCommit, ...(a.data?.pr?.commits ?? [])].includes(commit))
      add(a.session, 'annotation-link');
  }
  const available = new Set(store.sessions.map(s => s.ref));
  return {
    commits: analyses, diagnostics,
    sessions: [...candidates].sort(([a], [b]) => a.localeCompare(b)).map(([ref, reasons]) => {
      const found = store.sessions.filter(s => s.ref === ref);
      return { session: ref, reasons: [...reasons], details: found.length === 1 ? sessionSummary(found[0], available) : undefined };
    }),
  };
}

function escape(value: unknown): string {
  return String(value).replace(/[\x00-\x1f\x7f]/g, ' ').replace(/[\\`*_[\]{}()!|#]/g, '\\$&')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/@/g, '&#64;');
}
export function renderSummary(report: Report, sessionBaseUrl?: string): string {
  const output = [marker, '### Agent sessions', '', 'Recorded evidence is a match, not proof of authorship.', ''];
  for (const c of report.commits) {
    const edits = c.lines.filter(l => l.editedBy && l.editedBy.actor !== 'external'), competing = c.lines.filter(l => l.competing);
    output.push(`Commit \`${c.commit}\``, '', `Committed by: ${c.committedBy.length ? c.committedBy.map(x => escape(x.record)).join(', ') : 'unknown'}.`,
      `Edited lines: ${edits.length}. Competing lines: ${competing.length}. Other added lines: ${c.lines.length - edits.length - competing.length}.`, '');
    const groups = new Map<string, number>();
    for (const line of edits) {
      const e = line.editedBy!;
      const label = e.actor === 'human' ? `person (${escape(e.record)})` : escape(e.record);
      groups.set(label, (groups.get(label) ?? 0) + 1);
    }
    for (const [ref, count] of groups) output.push(`- Edited by ${ref}: ${count} line(s).`);
    for (const line of competing) output.push(`- Competing edit links: ${line.competing!.map(e => escape(e.record)).join(', ')}.`);
    if (groups.size || competing.length) output.push('');
  }
  if (!report.sessions.length) output.push('No session evidence was found. Attribution remains unknown.', '');
  for (const s of report.sessions) {
    const locator = sessionBaseUrl ? `[${escape(s.session)}](${sessionUrl(sessionBaseUrl, s.session).replace(/[()]/g, c => c === '(' ? '%28' : '%29')})` : escape(s.session);
    output.push(`- Session ${locator}. Sources: ${s.reasons.join(', ')}.`);
    if (!s.details) { output.push('  Session file is unresolved.'); continue; }
    output.push(`  Declared losses: ${s.details.missing.length ? s.details.missing.map(escape).join(', ') : 'none declared, capture completeness unknown'}.`,
      `  Gaps: ${s.details.gaps.length}. Unresolved references: ${s.details.unresolved.length}. Reader diagnostics: ${s.details.diagnostics.length}.`,
      `  Recorded approvals: ${s.details.approvals.length}. Approval history completeness remains unknown.`);
    for (const approval of s.details.approvals) output.push(`  - ${escape(approval.ref)}: ${escape(approval.decision)}, decider ${approval.by === undefined ? 'unknown' : escape(approval.by)}, ${approval.pairing}.`);
    for (const gap of s.details.gaps) output.push(`  - Gap ${escape(gap.ref)}: ${escape(gap.reason)}.`);
    for (const ref of s.details.unresolved) output.push(`  - Unresolved reference: ${escape(ref)}.`);
  }
  output.push('', `Store and repository diagnostics: ${report.diagnostics.length + report.commits.reduce((n, c) => n + c.diagnostics.length, 0)}.`,
    'Transcript text, tool arguments, approval subjects and gap details are omitted.');
  return output.join('\n');
}

export class GitLabApi {
  base: string;
  token: string;
  fetcher: typeof fetch;
  constructor(base: string, token: string, fetcher: typeof fetch = fetch) {
    const url = new URL(base);
    if (url.username || url.password || url.search || url.hash
        || url.protocol !== 'https:' && !(url.protocol === 'http:' && ['127.0.0.1', '[::1]', 'localhost'].includes(url.hostname)))
      throw new Error('GitLab needs HTTPS or a loopback HTTP API base.');
    this.base = url.href.replace(/\/$/, ''); this.token = token; this.fetcher = fetcher;
  }
  async request(endpoint: string, method = 'GET', body?: RecordData): Promise<{ value: any; next: string | null }> {
    let response: Response;
    try {
      response = await this.fetcher(`${this.base}${endpoint}`, { method, redirect: 'error', signal: AbortSignal.timeout(30000),
        headers: { 'PRIVATE-TOKEN': this.token, 'Content-Type': 'application/json' },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    } catch { throw new Error('GitLab request failed.'); }
    if (!response.ok) throw new Error(`GitLab returned HTTP ${response.status}.`);
    let value: any;
    const reader = response.body?.getReader(), chunks: Uint8Array[] = [];
    let size = 0;
    try {
      if (reader) for (;;) {
        const { done, value: chunk } = await reader.read();
        if (done) break;
        size += chunk.length;
        if (size > 16 * 1024 * 1024) { await reader.cancel(); throw new Error('Response limit'); }
        chunks.push(chunk);
      }
      value = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    } catch { throw new Error('GitLab returned invalid or oversized JSON.'); }
    return { value, next: response.headers.get('x-next-page') };
  }
  async list(endpoint: string): Promise<RecordData[]> {
    const values: RecordData[] = [], seen = new Set<string>();
    let page = '1';
    for (let count = 0; count < 100; count++) {
      if (!/^[1-9][0-9]{0,6}$/.test(page) || seen.has(page)) throw new Error('Invalid GitLab pagination.');
      seen.add(page);
      const response = await this.request(`${endpoint}?per_page=100&page=${page}`);
      if (!Array.isArray(response.value)) throw new Error('Expected a GitLab list.');
      values.push(...response.value);
      if (!response.next) return values;
      page = response.next;
    }
    throw new Error('GitLab pagination limit reached.');
  }
  mrPath(project: string, iid: number): string {
    if (!project || !Number.isSafeInteger(iid) || iid < 1) throw new Error('A project and positive merge request IID are required.');
    return `/projects/${encodeURIComponent(project)}/merge_requests/${iid}`;
  }
  async commits(git: Git, project: string, iid: number): Promise<string[]> {
    const endpoint = this.mrPath(project, iid), mr = (await this.request(endpoint)).value;
    const members = (await this.list(`${endpoint}/commits`)).map(r => r.id);
    if (!members.every(fullId)) throw new Error('GitLab supplied an invalid commit ID.');
    const merge = mr.state === 'merged' ? mr.merge_commit_sha ?? mr.squash_commit_sha ?? undefined : undefined;
    if (merge !== undefined && !fullId(merge)) throw new Error('GitLab supplied an invalid merge commit.');
    return git.mergeRequestCommits(merge, members);
  }
  async postSummary(project: string, iid: number, body: string): Promise<{ action: string; id?: number }> {
    const endpoint = `${this.mrPath(project, iid)}/notes`, user = (await this.request('/user')).value;
    if (!Number.isSafeInteger(user.id)) throw new Error('GitLab did not identify the authenticated user.');
    const notes = await this.list(endpoint);
    const matching = notes.filter(n => n.author?.id === user.id && typeof n.body === 'string' && n.body.startsWith(`${marker}\n`));
    if (matching.length > 1) throw new Error('Several owned summary comments exist.');
    const existing = matching[0];
    if (existing?.body === body) return { action: 'unchanged', id: existing.id };
    if (existing && !Number.isSafeInteger(existing.id)) throw new Error('GitLab supplied an invalid note ID.');
    const result = await this.request(existing ? `${endpoint}/${existing.id}` : endpoint, existing ? 'PUT' : 'POST', { body });
    return { action: existing ? 'updated' : 'created', id: result.value.id };
  }
}
