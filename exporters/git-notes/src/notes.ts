import { Git } from './git.ts';
import { exactJson } from './git-ai.ts';
import { isReference } from './reader.ts';
import type { RecordData } from './reader.ts';

export const linkRef = 'refs/notes/agent-sessions';
export type Link = { session: string; url?: string };
export function safeUrl(value: string): string {
  const url = new URL(value);
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) throw new Error('Expected an HTTP session locator without credentials.');
  return url.href;
}
export function sessionUrl(base: string, ref: string): string {
  return `${safeUrl(base).replace(/\/$/, '')}/${encodeURIComponent(ref)}`;
}
export function parseLinks(text: string): RecordData {
  const note = exactJson(text);
  if (note.schema !== 'asr-links/1' || !Array.isArray(note.sessions)
      || note.sessions.some((s: RecordData) => !s || !isReference(s.session) || s.url !== undefined && typeof s.url !== 'string'))
    throw new Error('Unsupported session link note.');
  return note;
}
export function writeLinks(git: Git, commit: string, links: Link[]): boolean {
  const id = git.resolve(commit), old = git.note(id, linkRef);
  const note = old === undefined ? { schema: 'asr-links/1', sessions: [] } : parseLinks(old);
  const joined = new Map<string, RecordData>(note.sessions.map((s: RecordData) => [s.session, s]));
  for (const link of links) {
    if (!isReference(link.session)) throw new Error('Invalid ASR session reference.');
    if (link.url !== undefined) safeUrl(link.url);
    joined.set(link.session, { ...joined.get(link.session), ...link });
  }
  note.sessions = [...joined.values()].sort((a, b) => a.session.localeCompare(b.session));
  return git.writeNote(id, linkRef, `${JSON.stringify(note, null, 2)}\n`, old !== undefined);
}
export function trailers(message: string): string[] {
  // Only inspect the final trailer paragraph. A mention in the subject is not a trailer.
  const paragraph = message.trimEnd().split(/\n\s*\n/).at(-1) ?? '';
  if (!paragraph.split('\n').every(row => /^[A-Za-z][A-Za-z0-9-]*:\s*\S.*$/.test(row))) return [];
  return [...paragraph.matchAll(/^Agent-Session:\s*(\S+)\s*$/gmi)].map(m => m[1]).filter(isReference).map(ref => ref.split('#')[0]);
}
