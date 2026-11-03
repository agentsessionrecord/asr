import { Git, fullId, addedByEdit } from './git.js';
import { type Data, type Session, type Store, encode, splitRef, original, unique, missing } from './store.js';

export interface PullRequest {
  repository: string;
  number: number;
  head: string;
  commits: string[];
  merged?: boolean;
  mergeCommit?: string;
}
export interface Citation { session: string; record: string }
export interface CommitCredit extends Citation { commit: string; recordedCommit: string; actor: string }
export interface EditCredit extends Citation {
  commit: string; path: string; line: number; introducingCommit: string;
  actor: string; call?: string; inference?: string; model?: string; modelKind?: string;
  prompts: string[]; alternatives: Citation[]; competing: boolean;
}
export interface SessionSummary {
  session: string; reasons: string[]; missing: string[];
  approvals: { record: string; decision: string; by: string; scope: string; call?: string; paired: boolean; copied: boolean }[];
  gaps: { record: string; reason: string; copied: boolean }[];
  truncated: string[]; issues: string[];
}
export interface Relationship { parent: string; child: string; kind: string; calls: string[]; sources: Citation[] }
export interface Report {
  repository: string; number: number; head: string; commits: string[];
  committedBy: CommitCredit[]; editedBy: EditCredit[]; sessions: SessionSummary[];
  unresolved: string[]; issues: string[]; relationships: Relationship[];
}
const commitActions = new Set(['commit', 'amend', 'merge', 'rebase', 'cherry_pick', 'revert']);
function success(session: Session, record: Data): boolean {
  if (record.status === 'completed') return true;
  if (record.status !== 'unknown') return false;
  const call = unique(session, 'tool_call', 'callId', record.callId);
  const result = unique(session, 'tool_result', 'callId', record.callId);
  return !!call && !!result && result.status === 'completed' && original(session, call) && original(session, result);
}
function prMatches(pr: any, target: PullRequest): boolean {
  if (!pr || typeof pr !== 'object') return false;
  if (pr.repository === target.repository && Number(pr.number) === target.number) return true;
  return pr.url === `https://github.com/${target.repository}/pull/${target.number}`;
}
function relatedCommit(data: Data, commits: Set<string>, git: Git): boolean {
  return (typeof data.commit === 'string' && commits.has(data.commit))
    || (Array.isArray(data.rewrites) && data.rewrites.some((pair: any) => commits.has(pair?.from) || commits.has(pair?.to)))
    || (typeof data.commitPrefix === 'string' && [...commits].some(c => c.startsWith(data.commitPrefix) && git.checks(data, c)));
}
function resolvedRecord(store: Store, reference: string): boolean {
  const target = splitRef(reference);
  const session = target && store.sessions.get(target.session);
  return !!session && (target!.record === undefined || session.records.filter(r => r.id === target!.record).length === 1);
}
function carriedPath(git: Git, session: Session, record: Data): string | undefined {
  return git.resolvePath(session, record.path);
}
export function buildReport(git: Git, store: Store, pr: PullRequest): Report {
  if (!fullId(pr.head) || !git.exists(pr.head)) throw new Error('Pull request head unavailable locally');
  const report: Report = { repository: pr.repository, number: pr.number, head: pr.head, commits: [],
    committedBy: [], editedBy: [], sessions: [], unresolved: [], issues: [...store.issues], relationships: [] };
  const reasons = new Map<string, Set<string>>();
  const add = (ref: string, reason: string) => {
    const target = splitRef(ref);
    if (!target) { report.issues.push('invalid-session-reference'); return; }
    if (!resolvedRecord(store, ref)) report.unresolved.push(ref);
    if (store.sessions.has(target.session)) {
      if (!reasons.has(target.session)) reasons.set(target.session, new Set());
      reasons.get(target.session)!.add(reason);
    }
  };
  let merge = pr.mergeCommit;
  if (pr.merged && !merge) {
    const recorded = new Set<string>();
    for (const session of store.sessions.values()) for (const record of session.records) {
      if (record.type === 'vcs' && original(session, record) && prMatches(record.pr, pr) && fullId(record.pr.mergeCommit)) recorded.add(record.pr.mergeCommit);
    }
    for (const { record } of store.annotations) if (['vcs', 'outcome'].includes(record.kind)
      && prMatches(record.data.pr, pr) && fullId(record.data.pr.mergeCommit)) recorded.add(record.data.pr.mergeCommit);
    if (recorded.size !== 1) throw new Error('Merged pull request has no unique merge commit');
    merge = [...recorded][0];
  }
  report.commits = [...new Set(pr.merged && merge ? git.members(merge) : pr.commits)];
  if (report.commits.length > 1000 || report.commits.some(c => !git.exists(c))) throw new Error('Pull request commits unavailable or over limit');
  const rewritePairs: { from: string; to: string }[] = [];
  const appendPairs = (record: Data) => {
    if (Array.isArray(record.rewrites)) for (const pair of record.rewrites) {
      if (pair?.from !== pair?.to && git.exists(pair?.from) && git.exists(pair?.to)) rewritePairs.push(pair);
    }
    else if (record.action === 'amend' && git.exists(record.headBefore) && git.exists(record.commit) && record.headBefore !== record.commit) {
      rewritePairs.push({ from: record.headBefore, to: record.commit });
    }
  };
  for (const session of store.sessions.values()) for (const record of session.records) {
    if (record.type === 'vcs' && original(session, record) && git.recordRepo(session, record) && success(session, record)) appendPairs(record);
  }
  for (const { record } of store.annotations) {
    const target = splitRef(record.session), session = target && store.sessions.get(target.session);
    if (record.kind === 'vcs' && record.data.status === 'completed'
      && (session ? git.recordRepo(session, record.data) : git.matchesRoot(record.data.repo))) appendPairs(record.data);
  }
  const histories = new Map<string, Set<string>>();
  for (const commit of report.commits) {
    const history = new Set([commit]), queue = [commit];
    while (queue.length) {
      const next = queue.pop()!;
      for (const pair of rewritePairs) if (pair.to === next && !history.has(pair.from)) { history.add(pair.from); queue.push(pair.from); }
    }
    histories.set(commit, history);
    for (const candidate of history) {
      // Git parses the actual trailer block. Body mentions are not trailers.
      const trailers = git.run(['-c', 'trailer.separators=:', 'show', '-s', '--format=%(trailers:key=Agent-Session,valueonly)', candidate]);
      for (const reference of trailers.split('\n').map(s => s.trim()).filter(Boolean)) add(reference, 'commit-trailer');
    }
  }
  const allCommits = new Set([...histories.values()].flatMap(s => [...s]));
  for (const { record } of store.annotations) {
    if (['vcs', 'outcome'].includes(record.kind) && (relatedCommit(record.data, allCommits, git) || prMatches(record.data.pr, pr))) add(record.session, 'annotation');
  }
  for (const session of store.sessions.values()) {
    for (const record of session.records) {
      if (record.type !== 'vcs' || !original(session, record) || !git.recordRepo(session, record)) continue;
      if (relatedCommit(record, allCommits, git)) add(session.ref, 'vcs-record');
      if (prMatches(record.pr, pr)) add(session.ref, record.action === 'pr_link' ? 'pr-reference' : ['pr_open', 'pr_merge'].includes(record.action)
        ? `${record.action}:${record.status === 'completed' ? 'completed' : 'unconfirmed'}` : 'pr-association');
      if (!commitActions.has(record.action) || !['observed', 'parsed_output'].includes(record.evidence) || !success(session, record)) continue;
      for (const [commit, history] of histories) for (const candidate of history) if (git.checks(record, candidate)) {
        report.committedBy.push({ session: session.ref, record: record.id, commit, recordedCommit: candidate, actor: record.actor ?? 'unknown' });
        add(session.ref, 'verified-commit');
      }
    }
  }
  for (const commit of report.commits) for (const [file, additions] of git.added(commit)) {
    const blamed = git.blame(commit, file);
    for (const line of additions) {
      const blame = blamed.get(line);
      if (!blame || !git.added(blame.commit).get(blame.path)?.has(blame.line)) continue;
      const target = git.blob(blame.commit, blame.path);
      if (target === undefined) continue;
      const candidates: EditCredit[] = [];
      for (const session of store.sessions.values()) {
        const matches: { record: Data; index: number }[] = [];
        session.records.forEach((record, index) => {
          if (record.type !== 'file_change' || record.status !== 'applied' || typeof record.op !== 'string' || !original(session, record)
            || (record.callId !== undefined && record.actor !== undefined) || (record.patch !== undefined && record.edits !== undefined)) return;
          let resolved = carriedPath(git, session, record);
          if (!resolved) return;
          // Preserve source edits through recorded later moves and copies in this stream.
          const destinations = new Set([resolved]);
          for (const later of session.records.slice(index + 1)) if (later.type === 'file_change' && later.status === 'applied'
            && original(session, later) && ['move', 'copy'].includes(later.op)) {
            const from = git.resolvePath(session, later.oldPath), to = git.resolvePath(session, later.path);
            if (from && to && destinations.has(from)) destinations.add(to);
          }
          if (!destinations.has(blame.path)) return;
          add(session.ref, 'file-touch');
          const parent = git.parents(blame.commit)[0];
          const newFile = !parent || git.blob(parent, blame.path) === undefined;
          if (addedByEdit(git, record, target, newFile).has(blame.line)) matches.push({ record, index });
        });
        if (!matches.length) continue;
        const record = matches.at(-1)!.record;
        if (record.actor === 'external') continue;
        const call = unique(session, 'tool_call', 'callId', record.callId);
        const inference = call && unique(session, 'inference', 'id', call.inferenceId);
        const model = typeof inference?.model?.id === 'string' ? inference.model.id : inference?.model?.requested;
        const prompts = call && typeof call.turnId === 'string' ? session.records.filter(r => r.type === 'message' && r.turnId === call.turnId
          && Array.isArray(r.content) && r.content.some((part: any) => (part?.author ?? r.author) === 'human'
            && ['prompt', 'queued', 'command', 'scheduled', undefined].includes(part?.origin ?? r.origin))).map(r => r.id) : [];
        candidates.push({ session: session.ref, record: record.id, commit, path: file, line, introducingCommit: blame.commit,
          actor: record.actor === 'human' ? 'human' : record.actor ?? (call ? 'session-tool' : 'unknown'), call: call?.id, inference: inference?.id,
          model: typeof model === 'string' ? model : undefined, modelKind: typeof inference?.model?.id === 'string' ? 'served' : 'requested',
          prompts, alternatives: matches.slice(0, -1).map(({ record: r }) => ({ session: session.ref, record: r.id })), competing: false });
        add(session.ref, 'surviving-edit-match');
      }
      for (const candidate of candidates) { candidate.competing = candidates.length > 1; report.editedBy.push(candidate); }
    }
  }
  for (const [reference, found] of reasons) {
    const session = store.sessions.get(reference)!;
    for (const record of session.records) {
      for (const ref of [record.type === 'session' ? record.parent?.session : undefined, record.copiedFrom?.session, record.subagent?.session, record.from]) {
        if (typeof ref === 'string' && !resolvedRecord(store, ref)) report.unresolved.push(ref);
      }
      if (typeof record.inferenceId === 'string' && !unique(session, 'inference', 'id', record.inferenceId)) report.unresolved.push(`${reference}#${encode(record.inferenceId)}`);
    }
    const parent = session.header.parent;
    if (typeof parent?.session === 'string' && typeof parent.record === 'string') {
      const target = `${parent.session}#${encode(parent.record)}`;
      if (!resolvedRecord(store, target)) report.unresolved.push(target);
    }
    for (const record of session.records) if (record.copiedFrom?.record && !record.copiedFrom?.session) {
      report.unresolved.push(`Copy source session unknown for record ${record.id}`);
    }
    report.sessions.push({ session: reference, reasons: [...found], missing: missing(session), issues: session.issues,
      approvals: session.records.filter(r => r.type === 'approval').map(r => ({ record: r.id,
        decision: typeof r.decision === 'string' ? r.decision : 'unknown', by: typeof r.by === 'string' ? r.by : 'unknown',
        scope: typeof r.scope === 'string' ? r.scope : 'unknown', call: typeof r.callId === 'string' ? r.callId : undefined,
        paired: !!unique(session, 'tool_call', 'callId', r.callId), copied: session.copied.has(r) })),
      gaps: session.records.filter(r => r.type === 'gap').map(r => ({ record: r.id, reason: typeof r.reason === 'string' ? r.reason : 'unknown', copied: session.copied.has(r) })),
      truncated: session.records.filter(r => r.truncated === true).map(r => r.id) });
  }
  const relationships = new Map<string, Relationship>();
  const relate = (parent: string, child: string, kind: string, call: unknown, source: Citation) => {
    if (!splitRef(parent) || !splitRef(child) || (!reasons.has(parent) && !reasons.has(child))) return;
    const key = JSON.stringify([parent, child, kind]);
    if (!relationships.has(key)) relationships.set(key, { parent, child, kind, calls: [], sources: [] });
    const relationship = relationships.get(key)!;
    if (typeof call === 'string' && !relationship.calls.includes(call)) relationship.calls.push(call);
    relationship.sources.push(source);
    for (const target of [parent, child]) if (!resolvedRecord(store, target)) report.unresolved.push(target);
  };
  for (const session of store.sessions.values()) {
    const parent = session.header.parent;
    if (typeof parent?.session === 'string' && typeof parent.kind === 'string') relate(parent.session, session.ref, parent.kind, parent.callId, { session: session.ref, record: session.header.id });
    for (const record of session.records) if (['tool_call', 'tool_result'].includes(record.type) && typeof record.subagent?.session === 'string') {
      relate(session.ref, record.subagent.session, 'subagent', record.callId, { session: session.ref, record: record.id });
    }
  }
  report.relationships = [...relationships.values()];
  report.unresolved = [...new Set(report.unresolved)];
  return report;
}

const safe = (value: string): string => [...value].map(c => /[a-zA-Z0-9 ._-]/.test(c) ? c : `&#${c.codePointAt(0)};`).join('');
export function sessionURL(base: string, reference: string, record?: string): string {
  const url = new URL(base);
  if ((url.protocol !== 'https:' && !(url.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)))
    || url.username || url.password || url.search || url.hash) throw new Error('Session base URL must be a trusted HTTPS directory URL');
  url.pathname = url.pathname.replace(/\/?$/, '/') + encodeURIComponent(reference).replace(/[!'()*]/g, c => `%${c.charCodeAt(0).toString(16).toUpperCase()}`);
  if (record !== undefined) url.hash = `record=${encodeURIComponent(record).replace(/[!'()*]/g, c => `%${c.charCodeAt(0).toString(16).toUpperCase()}`)}`;
  return url.href;
}
export function renderSummary(report: Report, base: string, limit = 50_000): string {
  const out: string[] = ['<!-- asr-github-summary -->', '## Agent Session Record', '',
    `${report.commits.length} verified local pull request commits. ${report.sessions.length} candidate sessions.`, '',
    'Edit matches and commit evidence are separate. Matches are recorded evidence, not proof of authorship.',
    'Approvals below cover the whole session. A recorded approval does not establish execution or success.',
    'Absent evidence stays unknown. No declared loss means completeness is unknown.', ''];
  const link = (reference: string, record?: string) => `[${safe(reference + (record === undefined ? '' : '#' + record))}](${sessionURL(base, reference, record)})`;
  const blocks: string[] = [];
  blocks.push('### Committed by\n\n' + (report.committedBy.length ? report.committedBy.map(c => `- ${safe(c.commit)}: ${link(c.session, c.record)}. Recorded commit ${safe(c.recordedCommit)}. Actor ${safe(c.actor)}.`).join('\n') : 'Unknown.'));
  blocks.push('### Edited by\n\n' + (report.editedBy.length ? report.editedBy.map(e => {
    const model = e.model === undefined ? 'Model unresolved' : `Model ${safe(e.model)} (${e.modelKind})`;
    return `- ${safe(e.path)} line ${e.line}: ${link(e.session, e.record)}. Actor ${safe(e.actor)}. ${model}. `
      + `Call ${e.call ? link(e.session, e.call) : 'unresolved'}. Inference ${e.inference ? link(e.session, e.inference) : 'unresolved'}. `
      + `Prompts ${e.prompts.length ? e.prompts.map(id => link(e.session, id)).join(', ') : 'unresolved'}. `
      + `${e.competing ? 'Competing sessions remain unresolved. ' : ''}`
      + `Earlier alternatives: ${e.alternatives.length ? e.alternatives.map(c => link(c.session, c.record)).join(', ') : 'none recorded'}.`;
  }).join('\n') : 'Unknown.'));
  for (const session of report.sessions) {
    blocks.push(`### ${link(session.session)}\n\nCandidate links: ${session.reasons.map(safe).join(', ')}.\n\n`
      + `Declared losses: ${session.missing.length ? session.missing.map(safe).join(', ') : 'none known'}.\n\n`
      + `Recorded approvals: ${session.approvals.length}.\n` + session.approvals.map(a => `- ${link(session.session, a.record)}: ${safe(a.decision)}, by ${safe(a.by)}, scope ${safe(a.scope)}. ${a.copied ? 'Copied decision.' : 'Original decision.'} ${a.call ? a.paired ? 'Call paired.' : 'Call unresolved.' : 'No call reference.'}`).join('\n')
      + `\n\nGaps: ${session.gaps.length}.\n` + session.gaps.map(g => `- ${link(session.session, g.record)}: ${safe(g.reason)}.${g.copied ? ' Copied gap.' : ''}`).join('\n')
      + `\n\nTruncated records: ${session.truncated.length}. Reader issues: ${session.issues.length}.`);
  }
  if (report.relationships.length) blocks.push('### Related sessions\n\n' + report.relationships.map(r => `- ${link(r.parent)} with ${link(r.child)} (${safe(r.kind)}). ${r.calls.length > 1 ? 'Conflicting call references.' : r.calls.length ? 'Recorded call reference available.' : 'Call unresolved.'}`).join('\n'));
  blocks.push(`### Unresolved references\n\n${report.unresolved.length ? report.unresolved.map(r => `- ${safe(r)}`).join('\n') : 'None found.'}\n\nStore reader issues: ${report.issues.length}.`);
  for (const block of blocks) {
    if (Buffer.byteLength([...out, block].join('\n\n')) > limit - 200) {
      out.push('Summary shortened for the GitHub size limit. Additional evidence and losses may be omitted. Use the local JSON report for full results.');
      break;
    }
    out.push(block);
  }
  return out.join('\n\n');
}
