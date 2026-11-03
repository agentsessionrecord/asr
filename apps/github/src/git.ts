import { execFileSync } from 'node:child_process';
import { realpathSync } from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { ExactNumber, type Data, type Session } from './store.js';

export const fullId = (value: unknown): value is string => typeof value === 'string' && /^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(value);
export const lines = (text: string): string[] => text.match(/[^\n]*\n|[^\n]+$/g) ?? [];
export interface BlamedLine { commit: string; path: string; line: number; text: string }
export class Git {
  readonly root: string;
  private cache = new Map<string, string>();
  constructor(directory: string, readonly recordedRoots: string[] = []) {
    this.root = realpathSync(directory);
    if (realpathSync(this.run(['rev-parse', '--show-toplevel']).trim()) !== this.root) throw new Error('Repository must name its root');
  }
  run(args: string[]): string {
    const environment = { ...process.env };
    for (const name of Object.keys(environment)) if (name.startsWith('GIT_')) delete environment[name];
    return execFileSync('git', ['--no-pager', '--literal-pathspecs', '-c', 'core.quotePath=false', '-c', 'core.fsmonitor=false',
      '-c', 'log.showSignature=false', '-c', 'core.hooksPath=/dev/null', '-C', this.root, ...args], {
      encoding: 'utf8', maxBuffer: 32 * 1024 * 1024, timeout: 30_000, stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...environment, GIT_TERMINAL_PROMPT: '0', GIT_NO_LAZY_FETCH: '1', GIT_NO_REPLACE_OBJECTS: '1', GIT_OPTIONAL_LOCKS: '0' },
    });
  }
  read(args: string[]): string {
    const key = JSON.stringify(args);
    if (!this.cache.has(key)) this.cache.set(key, this.run(args));
    return this.cache.get(key)!;
  }
  exists(commit: unknown): commit is string {
    if (!fullId(commit)) return false;
    try { return this.read(['cat-file', '-t', commit]).trim() === 'commit'; } catch { return false; }
  }
  parents(commit: string): string[] { return this.read(['show', '-s', '--format=%P', commit]).trim().split(' ').filter(Boolean); }
  subject(commit: string): string { return this.read(['show', '-s', '--format=%s', commit]).replace(/\n$/, ''); }
  members(merge: string): string[] {
    if (!this.exists(merge)) throw new Error('Merge commit unavailable locally');
    const parents = this.parents(merge);
    return parents.length < 2 ? [merge] : this.read(['rev-list', ...parents.slice(1), '--not', parents[0]]).trim().split('\n').filter(Boolean);
  }
  repoPaths(session: Session): string[] {
    return session.records.filter(r => r.type === 'session' || r.type === 'session_info').flatMap(r => Array.isArray(r.repos) ? r.repos : [])
      .filter(r => typeof r?.path === 'string').map(r => path.posix.normalize(r.path));
  }
  matchesRoot(root: unknown): root is string {
    return typeof root === 'string' && [this.root, ...this.recordedRoots].some(r => path.posix.normalize(r) === path.posix.normalize(root));
  }
  recordRepo(session: Session, record: Data): boolean {
    const roots = [...new Set(this.repoPaths(session))];
    return record.repo !== undefined ? this.matchesRoot(record.repo) && roots.includes(path.posix.normalize(record.repo))
      : roots.length === 1 && this.matchesRoot(roots[0]);
  }
  resolvePath(session: Session, value: unknown): string | undefined {
    if (typeof value !== 'string' || value.includes('\0') || value.includes('\\')) return;
    if (!path.posix.isAbsolute(value) && typeof session.header.cwd !== 'string') return;
    const absolute = path.posix.resolve(session.header.cwd ?? '/', value);
    const roots = this.repoPaths(session).filter(root => this.matchesRoot(root) && (absolute === root || absolute.startsWith(root + '/')))
      .sort((a, b) => b.length - a.length);
    if (!roots.length) return;
    const relative = path.posix.relative(roots[0], absolute);
    return relative && !relative.startsWith('../') ? relative : undefined;
  }
  checks(record: Data, candidate: string): boolean {
    if (!this.exists(candidate)) return false;
    const parents = this.parents(candidate);
    if (record.subject !== undefined && record.subject !== this.subject(candidate)) return false;
    if (record.parents !== undefined && (!Array.isArray(record.parents) || JSON.stringify(record.parents) !== JSON.stringify(parents))) return false;
    if (record.parentCount !== undefined && ((typeof record.parentCount !== 'number' && !(record.parentCount instanceof ExactNumber))
      || Number(record.parentCount) !== parents.length)) return false;
    if (record.commit !== undefined && record.commitPrefix !== undefined) return false;
    if (record.commit === candidate || (Array.isArray(record.rewrites) && record.rewrites.some((p: any) => p.to === candidate))) return true;
    if (typeof record.commitPrefix !== 'string' || !/^[a-f0-9]{7,39}$/.test(record.commitPrefix) || typeof record.subject !== 'string' || record.action === 'rebase') return false;
    const resolved = this.read(['rev-parse', `--disambiguate=${record.commitPrefix}`]).trim().split('\n');
    if (resolved.length !== 1 || resolved[0] !== candidate || (record.action === 'merge' ? parents.length < 2 : parents.length > 1)) return false;
    return !!this.read(['for-each-ref', '--format=%(refname)', `--contains=${candidate}`, 'refs/heads', 'refs/tags']).trim();
  }
  blob(commit: string, file: string): string | undefined {
    if (!this.exists(commit) || file.includes('\0')) return;
    try { return this.read(['cat-file', 'blob', `${commit}:${file}`]); } catch { return; }
  }
  state(state: any): string | undefined {
    if (!state || typeof state !== 'object') return;
    let text = typeof state.text === 'string' ? state.text : undefined;
    const object = state.objectId;
    if (object !== undefined) {
      const kind = state.objectIdType ?? 'git-blob-sha1';
      const algorithm = kind === 'git-blob-sha1' ? 'sha1' : 'sha256';
      if (typeof object !== 'string' || !new RegExp(`^[a-f0-9]{${algorithm === 'sha1' ? 40 : 64}}$`).test(object)) return;
      if (!['git-blob-sha1', 'git-blob-sha256', 'sha256'].includes(kind)) return;
      if (text === undefined && kind !== 'sha256') {
        try { text = this.read(['cat-file', 'blob', object]); } catch { return; }
      }
      if (text === undefined) return;
      const bytes = Buffer.from(text);
      const hash = createHash(algorithm);
      if (kind !== 'sha256') hash.update(`blob ${bytes.length}\0`);
      if (hash.update(bytes).digest('hex') !== object) return;
    }
    return text;
  }
  added(commit: string): Map<string, Set<number>> {
    if (!this.exists(commit)) throw new Error('Commit unavailable locally');
    const parent = this.parents(commit)[0];
    const args = parent ? ['diff', '--no-ext-diff', '--no-textconv', '--no-renames', '-U0', parent, commit]
      : ['diff-tree', '--root', '--no-commit-id', '-r', '-p', '--no-ext-diff', '--no-textconv', '--no-renames', '-U0', commit];
    const names = parent ? ['diff', '--name-only', '-z', '--no-renames', parent, commit]
      : ['diff-tree', '--root', '--no-commit-id', '-r', '--name-only', '-z', commit];
    const result = new Map<string, Set<number>>();
    for (const file of this.read(names).split('\0').filter(Boolean)) {
      if (this.blob(commit, file) === undefined) continue;
      let line = 0, inHunk = false;
      const added = new Set<number>();
      for (const row of this.read([...args, '--', file]).split('\n')) {
        const hunk = /^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(row);
        if (hunk) { line = Number(hunk[1]); inHunk = true; }
        else if (inHunk && row.startsWith('+')) added.add(line++);
        else if (inHunk && row.startsWith(' ')) line++;
      }
      if (added.size) result.set(file, added);
    }
    return result;
  }
  blame(commit: string, file: string): Map<number, BlamedLine> {
    const result = new Map<number, BlamedLine>(), content = lines(this.blob(commit, file) ?? '');
    let current: Partial<BlamedLine> = {}, final = 0;
    for (const row of this.read(['blame', '--root', '--no-textconv', '--line-porcelain', commit, '--', file]).split('\n')) {
      const head = /^([a-f0-9]{40}|[a-f0-9]{64}) (\d+) (\d+)(?: \d+)?$/.exec(row);
      if (head) { current = { commit: head[1], line: Number(head[2]) }; final = Number(head[3]); }
      else if (row.startsWith('filename ')) {
        const value = row.slice(9);
        try { current.path = value.startsWith('"') ? JSON.parse(value) : value; } catch { current.path = undefined; }
      } else if (row.startsWith('\t') && current.commit && current.path && current.line) {
        result.set(final, { ...current, text: content[final - 1] } as BlamedLine);
      }
    }
    return result;
  }
}

export function occurrences(haystack: string[], needle: string[]): number[] {
  if (!needle.length) return [];
  const found: number[] = [];
  outer: for (let at = 0; at <= haystack.length - needle.length; at++) {
    for (let i = 0; i < needle.length; i++) if (haystack[at + i] !== needle[i]) continue outer;
    found.push(at);
  }
  return found;
}
// Only wholly new, unique lines are credited from state and replacement evidence.
// Conservatively leave repeated lines and alignments unresolved.
export function addedByEdit(git: Git, record: Data, target: string, newFile: boolean): Set<number> {
  const result = new Set<number>(), targetLines = lines(target);
  const match = (oldText: string, newText: string, whole: boolean) => {
    const before = lines(oldText), after = lines(newText);
    if (!whole && (!newText || target.indexOf(newText) < 0 || target.indexOf(newText) !== target.lastIndexOf(newText))) return;
    const starts = whole ? [0] : occurrences(targetLines, after);
    for (let i = 0; i < after.length; i++) {
      if (before.includes(after[i]) || after.filter(s => s === after[i]).length !== 1) continue;
      const matches = occurrences(targetLines, [after[i]]);
      if (matches.length !== 1) continue;
      if (!whole && (starts.length !== 1 || matches[0] !== starts[0] + i)) continue;
      result.add(matches[0] + 1);
    }
  };
  const before = git.state(record.before), after = git.state(record.after);
  if (before !== undefined && after !== undefined) match(before, after, true);
  else if (Array.isArray(record.edits)) {
    for (const edit of record.edits) if (typeof edit?.oldText === 'string' && typeof edit?.newText === 'string') match(edit.oldText, edit.newText, false);
  } else if (typeof record.patch === 'string') {
    let run: string[] = [], inHunk = false;
    const flush = () => {
      const matches = occurrences(targetLines, run);
      if (matches.length === 1) for (let i = 0; i < run.length; i++) result.add(matches[0] + i + 1);
      run = [];
    };
    for (const row of record.patch.split('\n')) {
      if (row.startsWith('@@ ')) { flush(); inHunk = true; }
      else if (inHunk && row.startsWith('+')) run.push(row.slice(1) + '\n');
      else if (inHunk && row.startsWith('\\ No newline') && run.length) run[run.length - 1] = run.at(-1)!.slice(0, -1);
      else flush();
    }
    flush();
  } else if (after !== undefined && record.op === 'add' && newFile) match('', after, true);
  return result;
}
