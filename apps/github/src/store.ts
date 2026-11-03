import { readdir, open, realpath } from 'node:fs/promises';
import { constants } from 'node:fs';
import path from 'node:path';

// Numbers outside the projection remain exact lexemes, including native data.
export class ExactNumber {
  constructor(readonly raw: string) {}
  valueOf() { return Number(this.raw); }
  toJSON() { return this.raw; }
}
export type Data = { type: string; id: string; [key: string]: any };
export interface Session {
  ref: string;
  header: Data;
  records: Data[];
  copied: Set<Data>;
  issues: string[];
}
export interface Annotation { record: Data; file: string }
export interface Store {
  sessions: Map<string, Session>;
  annotations: Annotation[];
  issues: string[];
}
export const encode = (value: string): string => value.replace(/[%:# \x00-\x1f\x7f]/gu, c => encodeURIComponent(c));
export const sessionRef = (r: Data): string => [r.agent.name, ...(r.namespace === undefined ? [] : [encode(r.namespace)]), encode(r.sessionId)].join(':');
export function splitRef(value: unknown): { session: string; record?: string } | undefined {
  if (typeof value !== 'string') return;
  const parts = value.split('#');
  const components = parts[0].split(':');
  if (parts.length > 2 || ![2, 3].includes(components.length) || components.some(s => !s)
    || !/^[a-zA-Z0-9.-]+$/.test(components[0])) return;
  try {
    for (const component of [...components.slice(1), ...parts.slice(1)]) {
      if (!component || /[\x00-\x20\x7f]/.test(component) || /%(?![0-9A-F]{2})/.test(component)) return;
      decodeURIComponent(component);
    }
  } catch { return; }
  return { session: parts[0], ...(parts.length === 2 ? { record: decodeURIComponent(parts[1]) } : {}) };
}
export function parseRecord(text: string): Data {
  const value = (JSON.parse as Function)(text, (_key: string, value: unknown, source: { source?: string }) => {
    if (typeof value !== 'number') return value;
    if (!source?.source) throw new Error('JSON numeric source support is required');
    return new ExactNumber(source.source);
  });
  const stack: (Set<string> | null)[] = [];
  for (const match of text.matchAll(/"(?:\\.|[^"\\])*"|[{}\[\]]/g)) {
    const token = match[0];
    if (token === '{') stack.push(new Set());
    else if (token === '[') stack.push(null);
    else if (token === '}' || token === ']') stack.pop();
    else if (/^\s*:/.test(text.slice(match.index! + token.length))) {
      const key = JSON.parse(token), keys = stack.at(-1);
      if (keys?.has(key)) throw new Error('Duplicate key');
      keys?.add(key);
    }
  }
  if (!value || Array.isArray(value) || typeof value !== 'object' || typeof value.type !== 'string'
    || typeof value.id !== 'string' || !value.id || value.id.length > 256 || /[\x00-\x1f\x7f]/.test(value.id)) throw new Error('Invalid envelope');
  return value;
}
export function readJSONL(bytes: Uint8Array): { records: Data[]; issues: string[] } {
  const records: Data[] = [], issues: string[] = [], ids = new Set<string>();
  let line = 0, start = 0;
  for (let end = 0; end < bytes.length; end++) {
    if (bytes[end] !== 10) continue;
    line++;
    try {
      const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes.subarray(start, end));
      const record = parseRecord(text);
      if (ids.has(record.id)) issues.push(`duplicate-id:${line}`);
      ids.add(record.id);
      records.push(record);
    } catch { issues.push(`malformed-line:${line}`); }
    start = end + 1;
  }
  if (start < bytes.length) issues.push(`incomplete-tail:${line + 1}`);
  return { records, issues };
}
export function makeSession(records: Data[], issues: string[] = []): Session | undefined {
  const header = records[0];
  if (!header || header.type !== 'session' || header.formatVersion !== '0.1'
    || typeof header.agent?.name !== 'string' || typeof header.sessionId !== 'string' || !header.sessionId
    || issues.includes('malformed-line:1')
    || (header.namespace !== undefined && (typeof header.namespace !== 'string' || !header.namespace))) return;
  const ref = sessionRef(header);
  if (!splitRef(ref)) return;
  const copied = new Set<Data>(records.filter(r => r.copiedFrom !== undefined));
  const boundary = header.parent?.copiedThrough;
  if (boundary !== undefined) {
    const end = records.findIndex((r, i) => i > 0 && r.id === boundary);
    if (end < 0) issues.push('unresolved-copied-boundary');
    for (const record of records.slice(1, end < 0 ? undefined : end + 1)) copied.add(record);
  }
  if (records.slice(1).some(r => r.type === 'session')) issues.push('extra-header');
  const session = { ref, header, records, copied, issues };
  for (const record of records) {
    if (record.type === 'tool_call' && !unique(session, 'tool_result', 'callId', record.callId)) issues.push('unknown-call-outcome');
    if (record.type === 'tool_result' && !unique(session, 'tool_call', 'callId', record.callId)) issues.push('unpaired-result');
    if (record.type === 'approval' && record.callId !== undefined && !unique(session, 'tool_call', 'callId', record.callId)) issues.push('unpaired-approval');
  }
  return session;
}
export const original = (session: Session, record: Data): boolean => !session.copied.has(record)
  && !session.issues.some(i => /^(duplicate-id|extra-header|unresolved-copied-boundary)/.test(i));
export const unique = (session: Session, type: string, field: string, value: unknown): Data | undefined => {
  if (typeof value !== 'string') return;
  const matches = session.records.filter(r => r.type === type && r[field] === value);
  return matches.length === 1 ? matches[0] : undefined;
};
export async function loadStore(directory: string): Promise<Store> {
  const root = await realpath(directory), store: Store = { sessions: new Map(), annotations: [], issues: [] };
  let files = 0, totalBytes = 0;
  const ambiguous = new Set<string>();
  async function walk(current: string, depth: number): Promise<void> {
    if (depth > 16) throw new Error('Store nesting limit exceeded');
    for (const entry of (await readdir(current, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) {
      const file = path.join(current, entry.name);
      if (entry.isDirectory()) await walk(file, depth + 1);
      else if (entry.isFile() && entry.name.endsWith('.jsonl')) {
        if (++files > 1000) throw new Error('Store file limit exceeded');
        const handle = await open(file, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
        let bytes: Buffer;
        try {
          const stat = await handle.stat();
          if (!stat.isFile() || stat.size > 64 * 1024 * 1024) throw new Error('Store file size limit exceeded');
          const chunks: Buffer[] = [];
          let size = 0;
          for (;;) {
            const chunk = Buffer.alloc(Math.min(64 * 1024, 64 * 1024 * 1024 - size + 1));
            const { bytesRead } = await handle.read(chunk, 0, chunk.length, null);
            if (!bytesRead) break;
            size += bytesRead; totalBytes += bytesRead;
            if (size > 64 * 1024 * 1024 || totalBytes > 256 * 1024 * 1024) throw new Error('Store byte limit exceeded');
            chunks.push(chunk.subarray(0, bytesRead));
          }
          bytes = Buffer.concat(chunks);
        } finally { await handle.close(); }
        const result = readJSONL(bytes);
        store.issues.push(...result.issues);
        if (entry.name.endsWith('.annotations.jsonl')) {
          const prior = new Map<string, Data>(), seen = new Set<string>();
          for (const record of result.records) {
            if (record.type !== 'annotation' || !splitRef(record.session) || typeof record.at !== 'string'
              || !Number.isFinite(Date.parse(record.at)) || !record.data || typeof record.data !== 'object') {
              store.issues.push('invalid-annotation'); continue;
            }
            if (record.supersedes !== undefined) {
              if (typeof record.supersedes !== 'string' || !seen.has(record.supersedes)) {
                store.issues.push('invalid-supersedes'); continue;
              }
              prior.delete(record.supersedes);
            }
            seen.add(record.id);
            prior.set(record.id, record);
          }
          if (result.issues.some(i => i.startsWith('duplicate-id'))) continue;
          store.annotations.push(...[...prior.values()].map(record => ({ record, file })));
        } else {
          const session = makeSession(result.records, result.issues);
          if (!session) { store.issues.push('invalid-session'); continue; }
          if (store.sessions.has(session.ref) || ambiguous.has(session.ref)) {
            store.sessions.delete(session.ref); ambiguous.add(session.ref); store.issues.push('ambiguous-session');
          } else store.sessions.set(session.ref, session);
        }
      }
    }
  }
  await walk(root, 0);
  // Latest-value facts are scoped by exact target. VCS and test facts stay additive.
  store.annotations = store.annotations.filter(({ record: r }) => !['summary', 'title', 'outcome'].includes(r.kind)
    || !store.annotations.some(({ record: other }) => other.kind === r.kind && other.session === r.session && Date.parse(other.at) > Date.parse(r.at)));
  return store;
}
export function missing(session: Session): string[] {
  return [...new Set(session.records.filter(r => r.type === 'session' || r.type === 'session_info')
    .flatMap(r => Array.isArray(r.missing) ? r.missing.filter((s: unknown): s is string => typeof s === 'string') : []))];
}
