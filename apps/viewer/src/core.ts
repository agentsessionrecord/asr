import type { ASRRecord, Session, SessionInfo, AgentSettings, Inference, Annotation, Tools } from '../../../packages/types/src/index';

export type { ASRRecord, Session };
export const RECORD_LIMIT = 16 * 1024 * 1024;
export const RAW_PAGE = 64 * 1024;
export const INDEX_LIMIT = 250_000;

class ExactNumber extends Number {
  constructor(readonly source: string) { super(source); }
}

// JSON.parse's source context retains numeric lexemes, including unsafe integers.
// These objects never cross the worker boundary. Views contain formatted text.
export function parseRecord(text: string): ASRRecord {
  const value = (JSON.parse as Function)(text, (_key: string, value: unknown, context: { source?: string }) => {
    if (typeof value !== 'number') return value;
    if (!context?.source) throw new Error('This browser needs JSON source context support.');
    return new ExactNumber(context.source);
  });
  const keys: (Set<string> | null)[] = [];
  for (const match of text.matchAll(/"(?:\\.|[^"\\])*"|[{}\[\]]/g)) {
    const token = match[0];
    if (token === '{') keys.push(new Set());
    else if (token === '[') keys.push(null);
    else if (token === '}' || token === ']') keys.pop();
    else {
      let end = match.index! + token.length;
      while (/\s/.test(text[end] ?? '') && end < text.length) end++;
      if (text[end] === ':') {
        const key = JSON.parse(token), current = keys.at(-1);
        if (current?.has(key)) throw new Error('Duplicate object key.');
        current?.add(key);
      }
    }
  }
  if (!value || typeof value !== 'object' || Array.isArray(value) || typeof value.type !== 'string' || typeof value.id !== 'string'
    || !value.id.length || value.id.length > 256 || /[\x00-\x1f\x7f]/.test(value.id)) {
    throw new Error('Expected an ASR object with type and id.');
  }
  return value;
}

export function format(value: unknown, depth = 0): string {
  if (value === undefined) return 'unknown';
  if (value instanceof ExactNumber) return value.source;
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (depth > 64) return '"[nested data beyond display limit]"';
  if (Array.isArray(value)) return `[${value.map(v => format(v, depth + 1)).join(', ')}]`;
  return `{${Object.entries(value).map(([k, v]) => `${JSON.stringify(k)}: ${format(v, depth + 1)}`).join(', ')}}`;
}
export const label = (v: unknown): string => typeof v === 'string' ? v : format(v);
export const short = (v: unknown, limit = 180): string => label(v).slice(0, limit);
export const has = (v: object, key: string): boolean => Object.hasOwn(v, key);
export const encode = (s: string): string => s.replace(/[%:# \x00-\x1f\x7f]/gu, c => encodeURIComponent(c).replace(/%[\da-f]{2}/gi, s => s.toUpperCase()));
export const sessionRef = (s: Session): string => [s.agent.name, ...(s.namespace === undefined ? [] : [encode(s.namespace)]), encode(s.sessionId)].join(':');

export interface Line {
  start: number; length: number; line: number; text?: string; issue?: string;
}

// Keep at most one bounded line plus one chunk, never a decoded copy of the file.
export async function* readLines(file: Blob, chunkSize = 1024 * 1024): AsyncGenerator<Line> {
  let start = 0, line = 1, parts: Uint8Array[] = [], size = 0;
  const decoder = new TextDecoder('utf-8', { fatal: true });
  for (let offset = 0; offset < file.size; offset += chunkSize) {
    const bytes = new Uint8Array(await file.slice(offset, offset + chunkSize).arrayBuffer());
    let from = 0;
    for (let i = 0; i < bytes.length; i++) {
      if (bytes[i] !== 10) continue;
      const piece = bytes.subarray(from, i);
      size += piece.length;
      const entry: Line = { start, length: offset + i - start, line };
      if (size > RECORD_LIMIT) entry.issue = 'Record exceeds the 16 MiB decode limit. Inspect its original bytes in pages.';
      else {
        const all = new Uint8Array(size);
        let position = 0;
        for (const part of [...parts, piece]) { all.set(part, position); position += part.length; }
        try { entry.text = decoder.decode(all); }
        catch { entry.issue = 'Invalid UTF-8. Complete line skipped.'; }
      }
      yield entry;
      from = i + 1; start = offset + from; line++; parts = []; size = 0;
    }
    const tail = bytes.subarray(from);
    size += tail.length;
    if (size <= RECORD_LIMIT && tail.length) parts.push(tail.slice());
    else if (size > RECORD_LIMIT) parts = [];
  }
  if (start < file.size) yield { start, length: file.size - start, line, issue: 'Incomplete final line (no LF). Waiting for completion. Not used as a record.' };
}

export interface Entry extends Line {
  type: string; id: string; title: string; ts?: string; callId?: string;
  inferenceId?: string; copied: boolean; copiedFrom?: { session?: string; record?: string };
  truncated?: boolean;
  settingsAfter?: string; annotationState?: string;
  references: { session: string; record?: string; kind: string }[];
}
export interface PairGroup { calls: number[]; results: number[]; approvals: number[] }
export interface Accounting {
  model: string; calls: number; input: string; output: string; inputKnown: number; outputKnown: number;
  costs: Record<string, { amount: string; known: number }>;
}
export interface Summary {
  count: number; header?: Session; reference?: string; missing: string[]; issues: number;
  accounting: Accounting[]; relations: { session: string; record?: string; kind: string; at?: number }[];
  totals?: { usage?: string; cost?: string };
  annotations?: { id: string; target: string; kind: string; learnedAt: string; at: number; candidate: boolean }[];
}

function decimalParts(s: string): [bigint, number] {
  const [base, exponent = '0'] = s.toLowerCase().split('e');
  const fraction = base.split('.')[1]?.length ?? 0;
  const power = Number(exponent) - fraction;
  if (Math.abs(power) > 10000) throw new Error('Accounting exponent exceeds display limit');
  const integer = BigInt(base.replace('.', ''));
  return power >= 0 ? [integer * 10n ** BigInt(power), 0] : [integer, -power];
}
export function addDecimal(a: string, b: string): string {
  const [av, ap] = decimalParts(a), [bv, bp] = decimalParts(b), p = Math.max(ap, bp);
  const total = av * 10n ** BigInt(p - ap) + bv * 10n ** BigInt(p - bp);
  const sign = total < 0n ? '-' : '', digits = (total < 0n ? -total : total).toString().padStart(p + 1, '0');
  return sign + (p ? `${digits.slice(0, -p)}.${digits.slice(-p)}`.replace(/\.?0+$/, '') : digits);
}

export function updateSettings(previous: AgentSettings, update: AgentSettings): AgentSettings {
  const next = Object.assign(Object.create(null), previous);
  if (['mode', 'approval', 'sandbox'].some(k => has(update, k) && format(update[k]) !== format(previous[k])) && !has(update, 'asks')) delete next.asks;
  for (const [key, value] of Object.entries(update)) {
    if (key === 'modelSettings' && value !== null && typeof value === 'object') {
      next.modelSettings = Object.assign(Object.create(null), previous.modelSettings ?? {}, value);
      for (const [k, v] of Object.entries(next.modelSettings)) if (v === null) delete next.modelSettings[k];
    } else if (value === null) delete next[key];
    else next[key] = value;
  }
  return next;
}

export function titleFor(r: ASRRecord): string {
  switch (r.type) {
    case 'session': return `Session · ${short(r.title ?? r.sessionId)}`;
    case 'message': return `${short(r.role)} message · author ${short(r.author)} · origin ${short(r.origin)}`;
    case 'tool_call': return `Tool call · ${short(r.name)} · ${short(r.callId)}`;
    case 'tool_result': return `Tool result · ${short(r.status)} · ${short(r.callId)}`;
    case 'approval': return `Approval · ${short(r.decision)} · by ${short(r.by)} · scope ${short(r.scope)}`;
    case 'file_change': return `File change · ${short(r.op)} · ${short(r.path)}`;
    case 'vcs': return `Version control · ${short(r.action)} · ${short(r.status)}`;
    case 'inference': return 'Model call';
    case 'session_info': return 'Session update · settings, tools and totals';
    case 'gap': return `History gap · ${short(r.reason)}`;
    default: return `Unfamiliar record · ${short(r.type)}`;
  }
}

export class SessionIndex {
  constructor(private readonly maxEntries = INDEX_LIMIT) {}
  entries: Entry[] = [];
  header?: Session;
  groups = new Map<string, PairGroup>();
  ids = new Map<string, number[]>();
  missing = new Set<string>();
  issues = 0;
  settings: AgentSettings = {};
  latest: SessionInfo = { type: 'session_info', id: 'latest' };
  tools?: Tools;
  accounting = new Map<string, Accounting>();
  private pendingInference: { at: number; record: Inference }[] = [];
  private prefixEnd = -1;
  private annotations: { at: number; record: Annotation }[] = [];

  append(line: Line): void {
    if (this.entries.length >= this.maxEntries) throw new Error('Session index capacity reached.');
    let r: ASRRecord | undefined, issue = line.issue;
    if (!issue) {
      try { r = parseRecord(line.text!); } catch { issue = 'Malformed complete line. Skipped as a record.'; }
    }
    const at = this.entries.length;
    const e: Entry = {
      start: line.start, length: line.length, line: line.line, issue,
      type: r?.type ?? 'diagnostic', id: r?.id ?? `line-${line.line}`,
      title: r ? titleFor(r) : issue!, copied: !!r?.copiedFrom, references: [],
    };
    this.entries.push(e);
    if (!r) { this.issues++; return; }
    e.ts = typeof r.ts === 'string' ? r.ts : undefined;
    e.inferenceId = typeof r.inferenceId === 'string' ? r.inferenceId : undefined;
    e.copiedFrom = r.copiedFrom;
    e.truncated = r.truncated;
    const matches = this.ids.get(r.id) ?? [];
    matches.push(at); this.ids.set(r.id, matches);
    if (r.type === 'session' && line.line === 1) {
      if (r.formatVersion === '0.1' && typeof (r.agent as Session['agent'])?.name === 'string' && typeof r.sessionId === 'string') {
        this.header = r as Session;
        this.latest = { type: 'session_info', id: 'latest', title: this.header.title, endedAt: this.header.endedAt, repos: this.header.repos };
      }
      else { e.issue = 'Unsupported or malformed session header.'; this.issues++; }
    } else if (r.type === 'session') { e.issue = 'Additional session header. Not used as session identity.'; this.issues++; }
    if (r.type === 'session' || r.type === 'session_info') {
      if (Array.isArray(r.missing)) for (const loss of r.missing) if (typeof loss === 'string') this.missing.add(loss);
    }
    if (['tool_call', 'tool_result', 'approval', 'file_change', 'vcs'].includes(r.type) && typeof r.callId === 'string') {
      e.callId = r.callId;
      const group = this.groups.get(r.callId) ?? { calls: [], results: [], approvals: [] };
      if (r.type === 'tool_call') group.calls.push(at);
      if (r.type === 'tool_result') group.results.push(at);
      if (r.type === 'approval') group.approvals.push(at);
      this.groups.set(r.callId, group);
    }
    const subagent = r.subagent as { session?: string } | undefined;
    if (typeof subagent?.session === 'string') e.references.push({ session: subagent.session, kind: 'subagent' });
    if (typeof r.from === 'string') e.references.push({ session: r.from, kind: 'message from' });
    if (typeof r.copiedFrom?.session === 'string') e.references.push({ session: r.copiedFrom.session, record: r.copiedFrom.record, kind: 'copy source' });
    if (r.type === 'session_info' && r.agentSettings && typeof r.agentSettings === 'object') {
      this.settings = updateSettings(this.settings, (r as SessionInfo).agentSettings!);
      e.settingsAfter = format(this.settings).slice(0, 20000);
    }
    if (r.type === 'session_info') {
      const info = r as SessionInfo;
      for (const key of ['title', 'endedAt', 'usage', 'cost'] as const) if (has(info, key)) (this.latest as Record<string, unknown>)[key] = info[key];
      if (Array.isArray(info.repos)) this.latest.repos = [...this.latest.repos ?? [], ...info.repos];
      if (Array.isArray(info.tools)) this.tools = info.tools;
    }
    if (r.type === 'annotation' && typeof r.session === 'string') {
      const a = r as unknown as Annotation;
      this.annotations.push({ at, record: { type: 'annotation', id: a.id, kind: a.kind, at: a.at, session: a.session, supersedes: a.supersedes, source: { name: 'recorded' }, data: null } });
      e.title = `Later fact · ${short(a.kind)} · ${short(a.session)}`;
      const [session, record] = a.session.split('#');
      let decoded: string | undefined;
      try { decoded = record === undefined ? undefined : decodeURIComponent(record); } catch { /* Malformed reference stays unresolved. */ }
      e.references.push({ session, record: decoded, kind: 'annotation target' });
    }
    // Small accounting projections survive until the copied prefix is resolved.
    if (r.type === 'inference') {
      const inference = r as Inference;
      this.pendingInference.push({ at, record: { type: 'inference', id: r.id, model: inference.model, usage: inference.usage, cost: inference.cost } });
    }
  }

  finish(): Summary {
    const boundary = this.header?.parent?.copiedThrough;
    if (boundary !== undefined) {
      const matches = this.ids.get(boundary);
      if (matches?.length === 1 && matches[0] > 0) this.prefixEnd = matches[0];
      else this.issues++;
    }
    for (let i = 1; i <= this.prefixEnd; i++) this.entries[i].copied = true;
    const currentAnnotations = resolveAnnotations(this.annotations.map(a => a.record));
    for (const a of this.annotations) this.entries[a.at].annotationState = currentAnnotations.has(a.record.id) ? 'Current later fact. Separate from session actions.' : 'Historical later fact. Superseded or replaced.';
    const annotations = this.annotations.map(a => ({ id: a.record.id, target: a.record.session, kind: a.record.kind, learnedAt: annotationTime(a.record.at), at: a.at, candidate: currentAnnotations.has(a.record.id) }));
    this.annotations = [];
    this.accounting.clear();
    for (const { at, record: r } of this.pendingInference) {
      if (this.entries[at].copied) continue;
      const model = r.model?.id ? `${r.model.provider ?? 'unknown provider'} / ${r.model.id} (served)` : `${r.model?.requested ?? 'unknown model'} (requested)`;
      const row = this.accounting.get(model) ?? { model, calls: 0, input: '0', output: '0', inputKnown: 0, outputKnown: 0, costs: Object.create(null) };
      row.calls++;
      for (const [field, total, count] of [['inputTokens', 'input', 'inputKnown'], ['outputTokens', 'output', 'outputKnown']] as const) {
        const value = r.usage?.[field];
        if (value !== undefined) {
          try { row[total] = addDecimal(row[total], label(value)); row[count]++; } catch { this.issues++; }
        }
      }
      if (r.cost && typeof r.cost.currency === 'string') {
        const cost = row.costs[r.cost.currency] ?? { amount: '0', known: 0 };
        try { cost.amount = addDecimal(cost.amount, label(r.cost.amount)); cost.known++; } catch { this.issues++; }
        row.costs[r.cost.currency] = cost;
      }
      this.accounting.set(model, row);
    }
    this.pendingInference = [];
    const relations: Summary['relations'] = [];
    const parent = this.header?.parent;
    if (parent) relations.push({ session: parent.session, record: parent.record, kind: `parent (${parent.kind})` });
    for (const [at, e] of this.entries.entries()) for (const ref of e.references) relations.push({ ...ref, at });
    if (boundary !== undefined && this.prefixEnd < 0) relations.push({ session: this.header!.parent!.session, record: boundary, kind: 'unresolved local copiedThrough boundary' });
    const summaryHeader = this.header ? { ...this.header } : undefined;
    if (summaryHeader) for (const key of ['title', 'endedAt', 'repos'] as const) if (this.latest[key] !== undefined) (summaryHeader as Record<string, unknown>)[key] = this.latest[key];
    return { count: this.entries.length, header: summaryHeader ? JSON.parse(format(summaryHeader)) : undefined,
      reference: this.header ? sessionRef(this.header) : undefined, missing: [...this.missing], issues: this.issues,
      accounting: [...this.accounting.values()], relations, annotations, totals: { usage: this.latest.usage === undefined ? undefined : format(this.latest.usage), cost: this.latest.cost === undefined ? undefined : format(this.latest.cost) } };
  }

  pair(at: number): { call?: number; result?: number; approvals: number[]; note: string } {
    const e = this.entries[at], g = e?.callId === undefined ? undefined : this.groups.get(e.callId);
    if (!g || g.calls.length !== 1) return { approvals: [], note: e?.type === 'tool_call' ? 'Outcome unknown. Call ID is ambiguous.' : 'Unpaired. No unique matching call.' };
    return { call: g.calls[0], result: g.results.length === 1 ? g.results[0] : undefined, approvals: g.approvals,
      note: g.results.length === 1 ? 'Paired by unique call ID.' : g.results.length > 1 ? 'Multiple results. Outcome unresolved.' : 'Outcome unknown. No result recorded.' };
  }
}

export interface Section { title: string; text: string; kind?: 'diff' | 'text' }
export interface View {
  at: number; entry: Entry; sections: Section[]; pair?: ReturnType<SessionIndex['pair']>;
  inference?: number; unresolved?: string; references: Entry['references'];
}
export function sectionsFor(r: ASRRecord): Section[] {
  const sections: Section[] = [];
  const add = (title: string, value: unknown, kind?: Section['kind']) => {
    if (value !== undefined) sections.push({ title, text: label(value), kind });
  };
  if (r.type === 'message' || r.type === 'tool_result') {
    const content = r.content;
    if (Array.isArray(content)) {
      if (!content.length) add('Content', 'Recorded empty content array');
      for (const p of content) {
        if (!p || typeof p !== 'object') continue;
        const title = `${p.type} · author ${p.author ?? r.author ?? 'unknown'} · origin ${p.origin ?? r.origin ?? 'unknown'}`;
        if (p.type === 'text') add(title, p.text, 'text');
        else if (p.type === 'reasoning') {
          add(`Reasoning (${p.visibility ?? 'unknown visibility'})`, p.visibility === 'encrypted' || p.visibility === 'omitted' ? 'Content unavailable' : p.text ?? p.summary, 'text');
        } else if (p.type === 'resource_link') add('Resource link (recorded, never fetched)', { uri: p.uri, name: p.name });
        else if (p.type === 'resource') add('Embedded resource (recorded, never fetched)', { uri: p.resource?.uri, text: p.resource?.text, mimeType: p.resource?.mimeType });
        else if (p.type === 'image' || p.type === 'audio') add(`Recorded ${p.type}`, `${p.mimeType ?? 'unknown MIME type'} · ${p.data === undefined ? 'bytes not captured' : 'bytes present, not executed or loaded'}`);
      }
    }
    if (r.type === 'message') for (const key of ['phase', 'status', 'person']) add(key, r[key]);
    else for (const key of ['exec', 'error', 'durationMs', 'approvalId']) add(key, r[key]);
  }
  if (['tool_call', 'tool_result'].includes(r.type)) {
    if (has(r, 'input')) add(r.type === 'tool_result' ? 'Effective input learned at completion' : 'Recorded input', r.input);
    if (has(r, 'inputText')) add(r.type === 'tool_result' ? 'Effective input learned at completion' : 'Recorded input', r.inputText, 'text');
    for (const key of ['requestedBy', 'kind', 'locations', 'subagent', 'parentCallId']) add(key, r[key]);
  }
  if (r.type === 'file_change') {
    for (const key of ['status', 'oldPath', 'actor', 'baseCommit']) add(key, r[key]);
    if (typeof r.patch === 'string') add('Recorded unified diff', r.patch, 'diff');
    else if (Array.isArray(r.edits)) for (const edit of r.edits) {
      add('Recorded replacement (positions unknown)', `--- old snippet\n${edit.oldText.split('\n').map((s: string) => '-' + s).join('\n')}\n+++ new snippet\n${edit.newText.split('\n').map((s: string) => '+' + s).join('\n')}`, 'diff');
    } else if (r.before || r.after) {
      add('Recorded before state', r.before); add('Recorded after state', r.after);
      const before = (r.before as { text?: string } | undefined)?.text, after = (r.after as { text?: string } | undefined)?.text;
      if (typeof before === 'string' && typeof after === 'string') sections.unshift({ title: 'Display comparison of recorded states', text: compareStates(before, after), kind: 'diff' });
    } else add('Edit evidence', 'File touched. No recorded diff or text.');
  }
  if (r.type === 'session_info') for (const key of ['title', 'endedAt', 'agentSettings', 'tools', 'usage', 'cost', 'missing', 'repos']) add(key === 'usage' || key === 'cost' ? `Reported session total (${key}, separate from per-call sums)` : key, r[key]);
  if (r.type === 'inference') {
    const model = (r as Inference).model;
    add('Served model', model?.id ?? 'unknown'); add('Requested model', model?.requested ?? 'unknown');
    for (const key of ['usage', 'cost', 'settings', 'stopReason', 'durationMs', 'error']) add(key, r[key] ?? (key === 'usage' || key === 'cost' ? 'unknown' : undefined));
    add('Provider', model?.provider ?? 'unknown');
  }
  if (r.type === 'approval') for (const key of ['decision', 'by', 'scope', 'subject', 'person', 'native']) add(key, r[key]);
  if (r.type === 'vcs') for (const key of ['action', 'evidence', 'commit', 'commitPrefix', 'subject', 'repo', 'branch', 'remote', 'pr', 'parents', 'parentCount', 'headBefore', 'headAfter', 'rewrites', 'actor']) add(key, r[key]);
  if (r.type === 'gap') for (const key of ['reason', 'count', 'detail']) add(key, r[key]);
  if (r.type === 'annotation') for (const key of ['kind', 'at', 'source', 'data', 'supersedes']) add(key, r[key]);
  if (r.type === 'session') for (const key of ['agent', 'producer', 'user', 'startedAt', 'endedAt', 'cwd', 'repos', 'parent', 'derivedFrom', 'missing']) add(key, r[key]);
  return sections;
}

export function resolveAnnotations(annotations: Annotation[]): Set<string> {
  const corrected = new Set<string>();
  const earlier = new Set<string>();
  for (const a of annotations) {
    if (a.supersedes && earlier.has(a.supersedes)) corrected.add(a.supersedes);
    earlier.add(a.id);
  }
  const latest = new Map<string, string>();
  for (const a of annotations) {
    if (corrected.has(a.id) || !['summary', 'outcome', 'title'].includes(a.kind)) continue;
    const key = JSON.stringify([a.session, a.kind]), time = annotationTime(a.at);
    if (!latest.has(key) || latest.get(key)! < time) latest.set(key, time);
  }
  return new Set(annotations.filter(a => !corrected.has(a.id) && (['vcs', 'test'].includes(a.kind)
    || latest.get(JSON.stringify([a.session, a.kind])) === annotationTime(a.at))).map(a => a.id));
}
const annotationTime = (at: string): string => {
  if (!Number.isFinite(Date.parse(at))) return '';
  const fraction = /\.([0-9]+)(?:Z|[+-]\d{2}:\d{2})$/i.exec(at)?.[1].replace(/0+$/, '') || '0';
  return `${new Date(at).toISOString().slice(0, 19)}.${fraction}`;
};

export function compareStates(before: string, after: string): string {
  const oldLines = before.split('\n'), newLines = after.split('\n');
  let prefix = 0, suffix = 0;
  while (prefix < oldLines.length && prefix < newLines.length && oldLines[prefix] === newLines[prefix]) prefix++;
  while (suffix < oldLines.length - prefix && suffix < newLines.length - prefix && oldLines.at(-suffix - 1) === newLines.at(-suffix - 1)) suffix++;
  const removed = oldLines.slice(prefix, oldLines.length - suffix), added = newLines.slice(prefix, newLines.length - suffix);
  if (!removed.length && !added.length) return 'Recorded states are identical.';
  const lines = [`--- recorded before\n+++ recorded after\n@@ -${prefix + 1},${removed.length} +${prefix + 1},${added.length} @@`, ...removed.slice(0, 2000).map(s => '-' + s), ...added.slice(0, 2000).map(s => '+' + s)];
  if (removed.length > 2000 || added.length > 2000) lines.push('[Display excerpt. Inspect recorded states for all text.]');
  return lines.join('\n');
}
