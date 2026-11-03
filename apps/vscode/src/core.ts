import { execFile } from 'node:child_process';
import { lstat, readdir, open, readFile } from 'node:fs/promises';
import path from 'node:path';
import { randomBytes } from 'node:crypto';

export type Settings = { executable: string; sessions: string[]; annotations: string[] };
export type Evidence = { session?: string; reference?: string; credit?: string; [key: string]: unknown };
export type Report = { editStatus: string; editedBy: Evidence[]; committedBy: Evidence[]; alternatives: Evidence[]; sessions: unknown[]; sourceErrors: string; relationships: unknown[]; [key: string]: unknown };

// Preserve every numeric token as display text, including unknown vendor values.
export function parseExact(text: string): any {
  let result = '', quoted = false, escape = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      result += c;
      if (escape) escape = false;
      else if (c === '\\') escape = true;
      else if (c === '"') quoted = false;
    } else if (c === '"') { quoted = true; result += c; }
    else if (c === '-' || /[0-9]/.test(c)) {
      const token = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(text.slice(i));
      if (!token) throw new Error('Invalid blame JSON');
      result += JSON.stringify(token[0]); i += token[0].length - 1;
    } else result += c;
  }
  return JSON.parse(result);
}
export function parseReport(text: string): Report {
  const value = parseExact(text);
  if (!value || typeof value.sourceErrors !== 'string' || typeof value.editStatus !== 'string' || !['editedBy', 'committedBy', 'alternatives', 'sessions', 'relationships'].every(k => Array.isArray(value[k]))) throw new Error('Unsupported asr blame output');
  return value;
}
export function validateSettings(settings: Settings) {
  if (!settings.executable || settings.executable.includes('\0')) throw new Error('Set the installed ASR executable in user settings.');
  if (!settings.sessions.length) throw new Error('Set asr.sessions in user settings.');
  if (![...settings.sessions, ...settings.annotations].every(p => path.isAbsolute(p) && !p.includes('\0'))) throw new Error('ASR stores must use absolute local paths.');
}
export async function blame(settings: Settings, repo: string, file: string, line: number, signal?: AbortSignal): Promise<Report> {
  validateSettings(settings);
  if (!Number.isSafeInteger(line) || line < 1) throw new Error('Invalid line');
  const args = ['blame', file, '--line', String(line), '--repo', repo];
  for (const p of settings.sessions) args.push('--sessions', p);
  for (const p of settings.annotations) args.push('--annotations', p);
  const stdout = await new Promise<string>((resolve, reject) => {
    execFile(settings.executable, args, { cwd: repo, timeout: 15000, maxBuffer: 16 * 1024 * 1024, signal, windowsHide: true, shell: false }, (error, stdout) => {
      if (error) reject(new Error(error.name === 'AbortError' ? 'ASR lookup cancelled.' : 'ASR lookup failed. Check the executable, Git repository, stores and timeout.'));
      else resolve(stdout);
    });
  });
  return parseReport(stdout);
}
export async function gitRoot(file: string): Promise<string> {
  return new Promise((resolve, reject) => execFile('git', ['-C', path.dirname(file), 'rev-parse', '--show-toplevel'], { timeout: 5000, maxBuffer: 1024 * 1024, windowsHide: true }, (error, stdout) => error ? reject(new Error('This file has no local Git repository.')) : resolve(stdout.trim())));
}
export function reportText(report: Report): string {
  const group = (name: string, values: Evidence[]) => `${name}\n${values.length ? values.map(v => `${v.reference ?? v.session ?? 'unresolved'} (${v.credit ?? 'unknown credit'})\n${JSON.stringify(v, null, 2)}`).join('\n') : 'Unknown. No matching recorded evidence.'}`;
  return [
    'ASR line evidence', `Edit status: ${report.editStatus}`, 'Matches are recorded evidence, not proof of authorship.',
    group('Edited by', report.editedBy), group('Committed by', report.committedBy), group('Earlier alternatives', report.alternatives),
    'Session losses, gaps, diagnostics and unresolved references', JSON.stringify(report.sessions, null, 2),
    'Source errors', JSON.stringify(report.sourceErrors, null, 2), 'Related sessions', JSON.stringify(report.relationships, null, 2),
  ].join('\n\n');
}
export function sessionCommand(reference: string): string {
  const query = encodeURIComponent(JSON.stringify([reference])).replace(/[!'()*]/g, c => '%' + c.charCodeAt(0).toString(16).toUpperCase());
  return 'command:asr.openSession?' + query;
}
export function sessionReference(header: any): string | undefined {
  if (header?.type !== 'session' || header.formatVersion !== '0.1' || typeof header.agent?.name !== 'string' || typeof header.sessionId !== 'string') return;
  const encode = (s: string) => s.replace(/[%:# \x00-\x1f\x7f-\x9f]/gu, c => encodeURIComponent(c));
  return [header.agent.name, ...(typeof header.namespace === 'string' ? [encode(header.namespace)] : []), encode(header.sessionId)].join(':');
}
export async function sessionFiles(roots: string[]): Promise<string[]> {
  const files: string[] = [];
  let seen = 0;
  async function walk(file: string, depth: number) {
    if (++seen > 10000 || depth > 32) throw new Error('ASR store scan limit exceeded. Configure a smaller store.');
    const stat = await lstat(file);
    if (stat.isSymbolicLink()) return;
    if (stat.isDirectory()) { for (const item of (await readdir(file)).sort()) await walk(path.join(file, item), depth + 1); }
    else if (stat.isFile() && file.endsWith('.jsonl') && !file.endsWith('.annotations.jsonl')) files.push(file);
  }
  for (const root of roots) await walk(root, 0);
  return [...new Set(files.map(file => path.resolve(file)))];
}
export async function findSession(roots: string[], reference: string): Promise<string> {
  const matches: string[] = [];
  for (const file of await sessionFiles(roots)) {
    const handle = await open(file, 'r');
    try {
      const buffer = Buffer.alloc(65536);
      const { bytesRead } = await handle.read(buffer, 0, buffer.length, 0);
      const end = buffer.subarray(0, bytesRead).indexOf(10);
      if (end < 0) continue;
      try { if (sessionReference(parseExact(buffer.subarray(0, end).toString('utf8'))) === reference.split('#')[0]) matches.push(file); } catch { /* An invalid header cannot resolve a reference. */ }
    } finally { await handle.close(); }
  }
  if (matches.length !== 1) throw new Error(matches.length ? 'Session reference is ambiguous in the configured store.' : 'Session is unresolved in the configured store.');
  return matches[0];
}
export async function viewerHtml(template: string, file: string): Promise<string> {
  const stat = await lstat(file);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 64 * 1024 * 1024) throw new Error('Viewer input must be a regular file of at most 64 MiB.');
  const encoded = (await readFile(file)).toString('base64');
  const nonce = randomBytes(24).toString('hex');
  const policy = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-${nonce}'; style-src 'unsafe-inline'; worker-src blob:; connect-src 'none'; img-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'">`;
  const loader = `<script nonce="${nonce}">const data=atob('${encoded}');const bytes=Uint8Array.from(data,c=>c.charCodeAt(0));const transfer=new DataTransfer();transfer.items.add(new File([bytes],'session.jsonl'));const input=document.getElementById('files');input.files=transfer.files;input.dispatchEvent(new Event('change'));</script>`;
  return template.replace('<head>', '<head>' + policy).replace(/<script>/g, `<script nonce="${nonce}">`).replace('</body>', loader + '</body>');
}
