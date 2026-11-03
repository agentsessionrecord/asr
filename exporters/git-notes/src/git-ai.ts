// Serialization and key generation adapted from git-ai (Apache-2.0).
// See ../NOTICE for the pinned source and the changes in this port.
import { createHash } from 'node:crypto';
import { fullId, safePath } from './git.ts';
import type { Analysis } from './attribution.ts';
import type { Diagnostic, RecordData, Session } from './reader.ts';
// @ts-expect-error The validator lexer has no TypeScript declaration.
import { duplicateKeys } from '../../../tools/validator/src/jsonl.js';

export type Range = [number, number];
export type Attestation = { path: string; key: string; ranges: Range[] };
export type Authorship = { attestations: Attestation[]; metadata: RecordData };
export const toolNames: Record<string, string> = { 'claude-code': 'claude', codex: 'codex' };
const digest = (text: string) => createHash('sha256').update(text, 'utf8').digest('hex');
export const sessionKey = (tool: string, nativeId: string) => `s_${digest(`${tool}:${nativeId}`).slice(0, 14)}`;
export const traceKey = (recordRef: string) => `t_${digest(recordRef).slice(0, 14)}`;

export function exactJson(text: string): RecordData {
  const value = (JSON.parse as any)(text, (_key: string, v: any, context: { source?: string }) =>
    typeof v === 'number' ? (JSON as any).rawJSON(context.source) : v);
  if (!value || Array.isArray(value) || typeof value !== 'object' || duplicateKeys(text).length)
    throw new Error('Expected a JSON object with unique keys.');
  return value;
}
export function formatRanges(ranges: Range[]): string {
  return [...ranges].sort((a, b) => a[0] - b[0]).map(([a, b]) => a === b ? `${a}` : `${a}-${b}`).join(',');
}
function parseRanges(text: string): Range[] {
  let previous = 0;
  return text.split(',').map(part => {
    const m = /^([1-9][0-9]*)(?:-([1-9][0-9]*))?$/.exec(part);
    if (!m) throw new Error('Invalid Git AI range.');
    const a = Number(m[1]), b = Number(m[2] ?? m[1]);
    if (!Number.isSafeInteger(b) || a <= previous || a > b) throw new Error('Invalid or overlapping Git AI range.');
    previous = b;
    return [a, b];
  });
}
export function parseAuthorship(text: string): Authorship {
  const rows = text.split(/\r?\n/), divider = rows.indexOf('---');
  if (divider < 0) throw new Error('Missing Git AI divider.');
  const metadata = exactJson(rows.slice(divider + 1).join('\n'));
  if (metadata.schema_version !== 'authorship/3.0.0' || !fullId(metadata.base_commit_sha)
      || !metadata.prompts || typeof metadata.prompts !== 'object' || Array.isArray(metadata.prompts))
    throw new Error('Unsupported Git AI metadata.');
  const attestations: Attestation[] = [];
  let file: string | undefined;
  for (const row of rows.slice(0, divider)) {
    if (!row.trim()) continue;
    if (row.startsWith('  ')) {
      const entry = /^  (s_[a-f0-9]{14}::t_[a-f0-9]{14}|h_[a-f0-9]{14}|[a-f0-9]{16}|[a-f0-9]{7}) (\S+)$/.exec(row);
      if (!file || !entry) throw new Error('Invalid Git AI attestation.');
      attestations.push({ path: file, key: entry[1], ranges: parseRanges(entry[2]) });
    } else {
      file = row.startsWith('"') && row.endsWith('"') ? row.slice(1, -1) : row;
      safePath(file);
      if (/^\s/.test(row) || file.includes('"')) throw new Error('Unsupported Git AI path.');
    }
  }
  return { attestations, metadata };
}
export function serializeAuthorship(note: Authorship): string {
  let output = '', current: string | undefined;
  for (const a of note.attestations) {
    safePath(a.path);
    if (a.path.includes('"') || /[\r\n]/.test(a.path)) throw new Error('Unsupported Git AI path.');
    if (a.path !== current) {
      output += `${/[ \t]/.test(a.path) ? `"${a.path}"` : a.path}\n`; current = a.path;
    }
    output += `  ${a.key} ${formatRanges(a.ranges)}\n`;
  }
  output += `---\n${JSON.stringify(note.metadata, null, 2)}\n`;
  parseAuthorship(output);
  return output;
}
export function authorshipCandidates(note: Authorship, sessions: Session[], tools = toolNames) {
  return note.attestations.map(a => {
    const key = a.key.split('::')[0];
    const record = a.key.startsWith('s_') ? note.metadata.sessions?.[key]
      : a.key.startsWith('h_') ? note.metadata.humans?.[key] : note.metadata.prompts[key];
    const agent = record?.agent_id;
    const candidates = agent ? sessions.filter(s => tools[s.header.agent.name] === agent.tool && s.header.sessionId === agent.id)
      .map(s => s.ref) : [];
    return { path: a.path, key: a.key, ranges: a.ranges, candidates,
      status: a.key.startsWith('h_') ? 'human-link' : candidates.length === 1 ? 'candidate' : candidates.length > 1 ? 'ambiguous' : 'unresolved' };
  });
}
function compact(numbers: number[]): Range[] {
  const ranges: Range[] = [];
  for (const n of [...new Set(numbers)].sort((a, b) => a - b)) {
    if (ranges.length && ranges.at(-1)![1] + 1 === n) ranges.at(-1)![1] = n;
    else ranges.push([n, n]);
  }
  return ranges;
}
export function makeAuthorship(analysis: Analysis, sessions: Session[], tools = toolNames): { note: Authorship; diagnostics: Diagnostic[] } {
  const diagnostics: Diagnostic[] = [], entries = new Map<string, { path: string; key: string; numbers: number[] }>();
  const metadata: RecordData = { schema_version: 'authorship/3.0.0', base_commit_sha: analysis.commit, prompts: {}, sessions: Object.create(null) };
  const models = new Map<string, Set<string>>(), refs = new Map<string, Set<string>>();
  for (const s of sessions) {
    const tool = tools[s.header.agent.name];
    if (!tool) continue;
    const key = sessionKey(tool, s.header.sessionId), set = refs.get(key) ?? new Set<string>();
    set.add(s.ref); refs.set(key, set);
  }
  for (const line of analysis.lines) if (line.editedBy?.model?.kind === 'served') {
    const e = line.editedBy, set = models.get(e.session) ?? new Set<string>();
    set.add(e.model!.value); models.set(e.session, set);
  }
  for (const line of analysis.lines) {
    const e = line.editedBy;
    if (!e || e.actor === 'human' || e.actor === 'external') continue;
    const s = sessions.find(s => s.ref === e.session), tool = s && tools[s.header.agent.name];
    let code: string | undefined;
    if (line.path === '---' || /["\r\n]/.test(line.path)) code = 'unsupported-git-ai-path';
    else if (!s || !tool) code = 'unmapped-git-ai-tool';
    else if (refs.get(sessionKey(tool, s.header.sessionId))!.size !== 1) code = 'ambiguous-git-ai-session-key';
    else if (e.model?.kind !== 'served') code = 'git-ai-needs-served-model';
    else if (models.get(e.session)?.size !== 1) code = 'git-ai-session-has-multiple-models';
    else if (e.actor !== undefined || !e.call) code = 'git-ai-needs-causing-call';
    if (code) { diagnostics.push({ code, session: e.session }); continue; }
    const sk = sessionKey(tool!, s!.header.sessionId), key = `${sk}::${traceKey(e.record)}`;
    metadata.sessions[sk] = { agent_id: { tool, id: s!.header.sessionId, model: e.model!.value } };
    const grouping = JSON.stringify([line.path, key]), group = entries.get(grouping) ?? { path: line.path, key, numbers: [] };
    group.numbers.push(line.line); entries.set(grouping, group);
  }
  const attestations = [...entries.values()].sort((a, b) => a.path.localeCompare(b.path) || a.key.localeCompare(b.key))
    .map(e => ({ path: e.path, key: e.key, ranges: compact(e.numbers) }));
  return { note: { attestations, metadata }, diagnostics };
}
