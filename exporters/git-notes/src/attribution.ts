import { createHash } from 'node:crypto';
import { Git, lines, recordPath, recordRepo, safePath } from './git.ts';
import type { RepoMap } from './git.ts';
import { citation, successful, uniqueCall } from './reader.ts';
import type { Diagnostic, RecordData, Session } from './reader.ts';

const commitActions = new Set(['commit', 'amend', 'merge', 'rebase', 'cherry_pick', 'revert']);
export type Credit = { session: string; record: string; commit: string };
export type Edit = {
  session: string; record: string; actor?: string; call?: string; prompt?: string;
  model?: { value: string; kind: 'served' | 'requested' }; alternatives?: string[];
};
export type LineCredit = { path: string; line: number; introducingCommit: string; editedBy?: Edit; untracked?: Edit; competing?: Edit[] };
export type Analysis = { commit: string; committedBy: Credit[]; lines: LineCredit[]; diagnostics: Diagnostic[] };

function checks(git: Git, r: RecordData, id: string, abbreviated: boolean): boolean {
  const info = git.info(id);
  if (r.subject !== undefined && r.subject !== info.subject) return false;
  if (r.parents !== undefined && JSON.stringify(r.parents) !== JSON.stringify(info.parents)) return false;
  if (r.parentCount !== undefined && r.parentCount !== info.parents.length) return false;
  if (!abbreviated) return true;
  if (typeof r.subject !== 'string' || r.action === 'rebase') return false;
  const resolved = git.try(['rev-parse', `--disambiguate=${r.commitPrefix}`])?.trim().split('\n').filter(Boolean);
  if (resolved?.length !== 1 || resolved[0] !== id) return false;
  if (r.action === 'merge' ? info.parents.length < 2 : info.parents.length > 1) return false;
  return !!git.try(['for-each-ref', `--contains=${id}`, '--format=%(refname)', 'refs/heads', 'refs/tags'])?.trim();
}

function predecessors(git: Git, id: string, sessions: Session[], annotations: RecordData[], maps: RepoMap): Set<string> {
  const pairs: { from: string; to: string }[] = [];
  function add(r: RecordData) {
    for (const p of Array.isArray(r.rewrites) ? r.rewrites : [])
      if (p.from !== p.to && git.exists(p.from) && git.exists(p.to)) pairs.push(p);
    if (r.action === 'amend' && !r.rewrites?.length && r.headBefore !== r.commit
        && git.exists(r.headBefore) && git.exists(r.commit)) pairs.push({ from: r.headBefore, to: r.commit });
  }
  for (const s of sessions) {
    for (const r of s.records) if (r.type === 'vcs' && successful(s, r) && recordRepo(git, s, r, maps)) add(r);
    for (const a of annotations) if (a.session.split('#')[0] === s.ref && a.kind === 'vcs'
        && a.data?.status === 'completed' && recordRepo(git, s, a.data, maps)) add(a.data);
  }
  const result = new Set([id]), pending = [id];
  while (pending.length) {
    const next = pending.pop();
    for (const p of pairs) if (p.to === next && !result.has(p.from)) { result.add(p.from); pending.push(p.from); }
  }
  return result;
}

// A line is added only if it cannot be matched in any optimal LCS alignment.
// This withholds repeated or ambiguous unchanged context. Large edits stay unresolved.
export function addedChunks(before: string, after: string): string[][] {
  const a = lines(before), b = lines(after), width = b.length + 1;
  if ((a.length + 1) * width > 2_000_000) return [];
  const suffix = new Uint32Array((a.length + 1) * width), prefix = new Uint32Array(suffix.length);
  for (let i = a.length - 1; i >= 0; i--) for (let j = b.length - 1; j >= 0; j--)
    suffix[i * width + j] = a[i] === b[j] ? 1 + suffix[(i + 1) * width + j + 1]
      : Math.max(suffix[(i + 1) * width + j], suffix[i * width + j + 1]);
  for (let i = 0; i < a.length; i++) for (let j = 0; j < b.length; j++)
    prefix[(i + 1) * width + j + 1] = a[i] === b[j] ? prefix[i * width + j] + 1
      : Math.max(prefix[i * width + j + 1], prefix[(i + 1) * width + j]);
  const maybeContext = new Set<number>();
  for (let i = 0; i < a.length; i++) for (let j = 0; j < b.length; j++)
    if (a[i] === b[j] && prefix[i * width + j] + 1 + suffix[(i + 1) * width + j + 1] === suffix[0]) maybeContext.add(j);
  const chunks: string[][] = [];
  let chunk: string[] = [];
  for (let j = 0; j < b.length; j++) {
    if (maybeContext.has(j)) { if (chunk.length) chunks.push(chunk); chunk = []; }
    else chunk.push(b[j]);
  }
  if (chunk.length) chunks.push(chunk);
  return chunks;
}

function stateText(git: Git, input: RecordData | undefined, nearby: (string | undefined)[]): string | undefined {
  if (!input) return undefined;
  const state = input;
  function matches(text: string): boolean {
    if (!state.objectId) return true;
    const kind = state.objectIdType ?? 'git-blob-sha1';
    if (!['git-blob-sha1', 'git-blob-sha256', 'sha256'].includes(kind)) return false;
    const bytes = Buffer.from(text), algorithm = kind === 'git-blob-sha1' ? 'sha1' : 'sha256';
    const data = kind === 'sha256' ? bytes : Buffer.concat([Buffer.from(`blob ${bytes.length}\0`), bytes]);
    return createHash(algorithm).update(data).digest('hex') === state.objectId;
  }
  if (typeof state.text === 'string') return matches(state.text) ? state.text : undefined;
  if (typeof state.objectId !== 'string' || !/^[a-f0-9]{40}(?:[a-f0-9]{24})?$/.test(state.objectId)) return undefined;
  if ((state.objectIdType ?? 'git-blob-sha1').startsWith('git-blob-')
      && git.try(['cat-file', '-t', state.objectId])?.trim() === 'blob') {
    const text = git.try(['cat-file', 'blob', state.objectId]);
    if (text !== undefined && matches(text)) return text;
  }
  return nearby.find(text => text !== undefined && matches(text));
}

function patchChunks(patch: string): string[][] {
  const chunks: string[][] = [];
  let chunk: string[] = [], inHunk = false;
  for (const row of patch.split('\n')) {
    if (row.startsWith('@@ ')) { if (chunk.length) chunks.push(chunk); chunk = []; inHunk = true; }
    else if (inHunk && row.startsWith('+')) chunk.push(`${row.slice(1)}\n`);
    else if (row === '\\ No newline at end of file' && chunk.length) chunk[chunk.length - 1] = chunk.at(-1)!.slice(0, -1);
    else if (inHunk && !row.startsWith('-')) { if (chunk.length) chunks.push(chunk); chunk = []; }
  }
  if (chunk.length) chunks.push(chunk);
  return chunks;
}

function chunksFor(git: Git, r: RecordData, id: string, file: string): string[][] {
  if (r.truncated) return [];
  const parents = git.info(id).parents, final = git.blob(id, file);
  const prior = parents[0] ? git.blob(parents[0], file) : undefined;
  const before = stateText(git, r.before, [prior, final]), after = stateText(git, r.after, [final, prior]);
  if (before !== undefined && after !== undefined) return addedChunks(before, after);
  if (Array.isArray(r.edits)) return r.edits.flatMap((e: RecordData) =>
    typeof e.oldText === 'string' && typeof e.newText === 'string' ? addedChunks(e.oldText, e.newText) : []);
  if (typeof r.patch === 'string') return patchChunks(r.patch);
  if (r.op === 'add' && after !== undefined && prior === undefined) return addedChunks('', after);
  return [];
}
function matchedLines(chunks: string[][], final: string[], added: Set<number>): Set<number> {
  const result = new Set<number>();
  let previous = -1;
  for (const chunk of chunks) {
    const positions: number[] = [];
    for (let i = 0; i <= final.length - chunk.length; i++) if (chunk.every((v, j) => v === final[i + j])) positions.push(i);
    if (positions.length !== 1 || positions[0] <= previous) continue;
    previous = positions[0] + chunk.length - 1;
    for (let j = 0; j < chunk.length; j++) if (added.has(positions[0] + j + 1)) result.add(positions[0] + j + 1);
  }
  return result;
}
function editDetails(s: Session, r: RecordData): Edit {
  const edit: Edit = { session: s.ref, record: citation(s, r) };
  if (r.actor !== undefined) edit.actor = r.actor;
  const call = uniqueCall(s, r.callId);
  if (!call) return edit;
  edit.call = citation(s, call);
  const inferences = s.records.filter(x => x.type === 'inference' && x.id === call.inferenceId);
  const inference = inferences.length === 1 ? inferences[0] : undefined;
  if (typeof inference?.model?.id === 'string') edit.model = { value: inference.model.id, kind: 'served' };
  else if (typeof inference?.model?.requested === 'string') edit.model = { value: inference.model.requested, kind: 'requested' };
  const turn = call.turnId ?? inference?.turnId;
  const prompts = s.records.filter(x => x.type === 'message' && x.turnId === turn && turn !== undefined
    && x.role === 'user' && x.origin === 'prompt' && Array.isArray(x.content)
    && x.content.some((p: RecordData) => (p.author ?? x.author) === 'human' && (p.origin ?? x.origin) === 'prompt'));
  if (prompts.length === 1) edit.prompt = citation(s, prompts[0]);
  return edit;
}

export function analyzeCommit(git: Git, ref: string, sessions: Session[], maps: RepoMap = [], annotations: RecordData[] = []): Analysis {
  const commit = git.resolve(ref), ancestors = predecessors(git, commit, sessions, annotations, maps);
  const committedBy: Credit[] = [], diagnostics: Diagnostic[] = [];
  for (const s of sessions) for (const r of s.records) {
    if (r.type !== 'vcs' || !s.original.has(r) || !commitActions.has(r.action) || !successful(s, r)
        || !['observed', 'parsed_output'].includes(r.evidence) || !recordRepo(git, s, r, maps)) continue;
    for (const id of ancestors) {
      const full = r.commit === id || r.rewrites?.some((p: RecordData) => p.to === id);
      const short = typeof r.commitPrefix === 'string' && /^[a-f0-9]{7,39}$/.test(r.commitPrefix) && id.startsWith(r.commitPrefix);
      if ((full || short) && !(r.commit && r.commitPrefix) && checks(git, r, id, !full))
        committedBy.push({ session: s.ref, record: citation(s, r), commit: id });
    }
  }
  const result: LineCredit[] = [];
  for (const file of git.files(commit)) {
    let added: Set<number>;
    try { safePath(file); added = git.added(commit, file); } catch { diagnostics.push({ code: 'unresolved-path' }); continue; }
    if (!added.size) continue;
    const text = git.blob(commit, file);
    if (text === undefined || text.includes('\0')) continue;
    const final = lines(text), blame = git.blame(commit, file);
    const matches = new Map<number, Map<string, Edit[]>>();
    for (const s of sessions) {
      // Carry source edits through explicit applied moves or copies. Carrying is not authorship.
      const candidates = new Map<string, { r: RecordData; chunks: string[][] }[]>();
      for (const r of s.records) {
        if (r.type !== 'file_change' || !s.original.has(r) || r.status !== 'applied') continue;
        const target = recordPath(git, s, r.path, maps);
        if (!target) continue;
        if (['move', 'copy'].includes(r.op)) {
          const source = recordPath(git, s, r.oldPath, maps);
          if (source && candidates.has(source)) candidates.set(target, [...(candidates.get(target) ?? []), ...candidates.get(source)!]);
          if (r.op === 'move' && source !== target) candidates.delete(source!);
        }
        const chunks = chunksFor(git, r, commit, target);
        if (chunks.length) candidates.set(target, [...(candidates.get(target) ?? []), { r, chunks }]);
      }
      const ordered = (candidates.get(file) ?? []).sort((a, b) => s.records.indexOf(a.r) - s.records.indexOf(b.r));
      for (const { r, chunks } of ordered) for (const line of matchedLines(chunks, final, added)) {
        const location = blame.get(line);
        if (!location || location.commit !== commit || location.path !== file || location.line !== line) continue;
        const group = matches.get(line) ?? new Map<string, Edit[]>();
        group.set(s.ref, [...(group.get(s.ref) ?? []), editDetails(s, r)]); matches.set(line, group);
      }
    }
    for (const line of added) {
      const group = matches.get(line), location = blame.get(line);
      const answer: LineCredit = { path: file, line, introducingCommit: location?.commit ?? commit };
      const latest = [...(group?.values() ?? [])].map(edits => ({ ...edits.at(-1)!, alternatives: edits.slice(0, -1).map(e => e.record) }));
      if (latest.length === 1 && latest[0].actor === 'external') answer.untracked = latest[0];
      else if (latest.length === 1) answer.editedBy = latest[0];
      else if (latest.length > 1) answer.competing = latest;
      result.push(answer);
    }
  }
  return { commit, committedBy, lines: result, diagnostics };
}
