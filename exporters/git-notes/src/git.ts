import { execFileSync } from 'node:child_process';
import { realpathSync } from 'node:fs';
import path from 'node:path';
import type { RecordData, Session } from './reader.ts';

export const fullId = (x: unknown): x is string => typeof x === 'string' && /^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(x);
export type RepoMap = { source: string; local: string }[];
export class Git {
  root: string;
  constructor(directory: string) {
    this.root = realpathSync(directory);
    this.root = realpathSync(this.run(['rev-parse', '--show-toplevel']).trim());
  }
  run(args: string[], input?: string): string {
    try {
      const environment = { ...process.env };
      for (const name of Object.keys(environment)) if (name.startsWith('GIT_')) delete environment[name];
      return execFileSync('git', ['--no-pager', '--literal-pathspecs', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
        '-c', 'core.quotePath=false', '-c', 'log.showSignature=false', '-c', 'commit.gpgSign=false', '-C', this.root, ...args], {
        input, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024, timeout: 30000,
        env: { ...environment, GIT_TERMINAL_PROMPT: '0', GIT_NO_REPLACE_OBJECTS: '1', GIT_NO_LAZY_FETCH: '1', GIT_OPTIONAL_LOCKS: '0' },
        stdio: ['pipe', 'pipe', 'pipe'],
      });
    } catch { throw new Error(`Local Git operation failed: ${args[0]}.`); }
  }
  try(args: string[]): string | undefined { try { return this.run(args); } catch { return undefined; } }
  resolve(ref: string): string {
    const id = this.run(['rev-parse', '--verify', '--end-of-options', `${ref}^{commit}`]).trim();
    if (!fullId(id)) throw new Error('Commit did not resolve to a full object ID.');
    return id;
  }
  exists(id: unknown): id is string { return fullId(id) && this.try(['cat-file', '-t', id])?.trim() === 'commit'; }
  info(id: string) {
    if (!fullId(id)) throw new Error('A full commit ID is required.');
    const [parents, subject] = this.run(['show', '-s', '--no-notes', '--format=%P%n%s', id]).replace(/\n$/, '').split('\n');
    return { parents: parents ? parents.split(' ') : [], subject: subject ?? '' };
  }
  blob(id: string, file: string): string | undefined { return this.try(['show', `${id}:${safePath(file)}`]); }
  files(id: string): string[] {
    return this.run(['ls-tree', '-r', '--name-only', '-z', id]).split('\0').filter(Boolean);
  }
  added(id: string, file: string): Set<number> {
    const parents = this.info(id).parents;
    if (!parents.length) return new Set(lines(this.blob(id, file) ?? '').map((_, i) => i + 1));
    const diff = this.run(['diff', '--no-ext-diff', '--no-textconv', '--no-renames', '--unified=0', parents[0], id, '--', file]);
    const added = new Set<number>();
    let line = 0;
    for (const row of diff.split('\n')) {
      const h = /^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(row);
      if (h) line = Number(h[1]);
      else if (line && row.startsWith('+') && !row.startsWith('+++')) added.add(line++);
      else if (line && row.startsWith(' ')) line++;
    }
    return added;
  }
  blame(id: string, file: string): Map<number, { commit: string; path: string; line: number }> {
    const output = this.try(['blame', '--line-porcelain', id, '--', safePath(file)]);
    const result = new Map<number, { commit: string; path: string; line: number }>();
    if (!output) return result;
    let commit = '', oldLine = 0, newLine = 0, oldPath = '';
    for (const row of output.split('\n')) {
      const h = /^([a-f0-9]{40}|[a-f0-9]{64}) (\d+) (\d+)(?: \d+)?$/.exec(row);
      if (h) { commit = h[1]; oldLine = Number(h[2]); newLine = Number(h[3]); }
      else if (row.startsWith('filename ')) {
        const p = row.slice(9);
        // Quoted special-byte paths require Git's C-string decoder. Withhold credit here.
        oldPath = p.startsWith('"') ? '' : p;
      } else if (row.startsWith('\t') && oldPath) result.set(newLine, { commit, path: oldPath, line: oldLine });
    }
    return result;
  }
  note(id: string, ref: string): string | undefined { return this.try(['notes', `--ref=${ref}`, 'show', id]); }
  writeNote(id: string, ref: string, text: string, replace = false): boolean {
    if (!fullId(id) || !/^refs\/notes\/[a-zA-Z0-9/_-]+$/.test(ref)) throw new Error('Invalid notes target.');
    const current = this.note(id, ref);
    if (current?.trimEnd() === text.trimEnd()) return false;
    if (current !== undefined && !replace) throw new Error('An existing note needs explicit replacement.');
    this.run(['notes', `--ref=${ref}`, 'add', ...(replace ? ['-f'] : []), '-F', '-', id], text);
    return true;
  }
  mergeRequestCommits(merge: string | undefined, members: string[]): string[] {
    if (!merge) return [...new Set(members)];
    const id = this.resolve(merge), parents = this.info(id).parents;
    if (parents.length < 2) return [id];
    return this.run(['rev-list', ...parents.slice(1), '--not', parents[0]]).trim().split('\n').filter(Boolean);
  }
}
export function safePath(file: string): string {
  if (!file || file.startsWith('/') || file.split('/').some(p => p === '..' || p === '.git') || /[\x00\r\n]/.test(file))
    throw new Error('Unsafe repository path.');
  return file;
}
export const lines = (text: string): string[] => text.match(/[^\n]*\n|[^\n]+$/g) ?? [];
const windowsPath = (value: string) => /^[A-Za-z]:[/\\]|^\\\\|^\/\/[^/]+\/[^/]+/.test(value);
const sourceAbsolute = (value: string) => path.posix.isAbsolute(value) || windowsPath(value);
const normalizeSource = (value: string) => windowsPath(value) ? path.win32.normalize(value).replace(/\\/g, '/') : path.posix.normalize(value);
function resolveSource(cwd: unknown, value: string): string | undefined {
  if (sourceAbsolute(value)) return normalizeSource(value);
  if (typeof cwd !== 'string' || !sourceAbsolute(cwd)) return undefined;
  return normalizeSource((windowsPath(cwd) ? path.win32 : path.posix).resolve(cwd, value));
}
export function repositories(s: Session): RecordData[] {
  const repos = [s.header, ...s.records.filter(r => r.type === 'session_info')].flatMap(r => Array.isArray(r.repos) ? r.repos : [])
    .map(r => ({ ...r, path: resolveSource(s.header.cwd, r.path) })).filter(r => r.path !== undefined);
  return [...new Map<string, RecordData>(repos.map(r => [r.path, r])).values()];
}
export function sourceRoot(git: Git, source: string, maps: RepoMap): boolean {
  if (!sourceAbsolute(source)) return false;
  const mapped = maps.filter(m => normalizeSource(m.source) === normalizeSource(source));
  try { return mapped.length ? mapped.length === 1 && realpathSync(mapped[0].local) === git.root : realpathSync(source) === git.root; }
  catch { return false; }
}
export function recordRepo(git: Git, s: Session, r: RecordData, maps: RepoMap): boolean {
  const repos = repositories(s);
  const source = r.repo === undefined ? (repos.length === 1 ? repos[0].path : undefined) : normalizeSource(r.repo);
  return typeof source === 'string' && repos.some(repo => repo.path === source) && sourceRoot(git, source, maps);
}
export function recordPath(git: Git, s: Session, value: unknown, maps: RepoMap): string | undefined {
  if (typeof value !== 'string') return undefined;
  const absolute = resolveSource(s.header.cwd, value);
  if (!absolute) return undefined;
  const candidates = repositories(s).filter(repo => typeof repo.path === 'string'
    && (absolute === repo.path || absolute.startsWith(`${repo.path.replace(/\/$/, '')}/`)))
    .sort((a, b) => b.path.length - a.path.length);
  if (!candidates.length || !sourceRoot(git, candidates[0].path, maps)) return undefined;
  try { return safePath(absolute.slice(candidates[0].path.replace(/\/$/, '').length + 1)); } catch { return undefined; }
}
