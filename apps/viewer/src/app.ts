import type { Summary, View, Section } from './core';
import { encode } from './core';
declare const ASR_WORKER_SOURCE: string;

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const node = <K extends keyof HTMLElementTagNameMap>(tag: K, text?: string, cls?: string): HTMLElementTagNameMap[K] => {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
};
const button = (text: string, action: () => void) => {
  const b = node('button', text); b.type = 'button'; b.onclick = action; return b;
};
interface OpenFile { id: number; name: string; summary: Summary; unsupported?: boolean }
let worker: Worker;
let opened: OpenFile[] = [], selected: OpenFile | undefined;
let serial = 0, version = 0, rendering = false, scheduled = false;
const pending = new Map<number, { resolve: (v: any) => void; reject: (e: Error) => void }>();
const timeline = $('timeline'), rows = $('rows'), spacer = $('spacer');
const rowHeight = 320;
let currentStart = -1, currentFile = -1;
let rawPosition = 0, detailAt = 0, detailFile = 0;
function logicalTop() {
  const count = selected?.summary.count ?? 0;
  const physical = Math.max(0, Math.min(8000000, count * rowHeight) - timeline.clientHeight);
  return physical ? timeline.scrollTop / physical * Math.max(0, count * rowHeight - timeline.clientHeight) : 0;
}
function jumpTo(at: number) {
  const total = (selected?.summary.count ?? 0) * rowHeight;
  const logical = Math.max(0, total - timeline.clientHeight), physical = Math.max(0, Math.min(8000000, total) - timeline.clientHeight);
  timeline.scrollTop = logical ? Math.min(logical, Math.max(0, at * rowHeight)) / logical * physical : 0;
  scheduleRender();
}

function rpc(kind: string, args: object = {}): Promise<any> {
  const request = ++serial;
  return new Promise((resolve, reject) => { pending.set(request, { resolve, reject }); worker.postMessage({ request, kind, ...args }); });
}
function resetWorker() {
  if (worker) worker.terminate();
  for (const p of pending.values()) p.reject(new Error('File selection changed'));
  pending.clear();
  const url = URL.createObjectURL(new Blob([ASR_WORKER_SOURCE], { type: 'text/javascript' }));
  worker = new Worker(url);
  URL.revokeObjectURL(url);
  worker.onerror = () => { $('status').textContent = 'The reader worker stopped. Try reopening fewer files.'; document.body.dataset.state = 'error'; $('cancel').hidden = true; };
  worker.onmessage = ({ data }) => {
    if (data.request) {
      const p = pending.get(data.request); pending.delete(data.request);
      if (data.kind === 'error') p?.reject(new Error(data.message)); else p?.resolve(data);
      return;
    }
    if (data.kind === 'file') {
      opened.push(data);
      renderFiles();
      if (!selected) selectFile(data.id);
      else renderFacts();
    } else if (data.kind === 'progress') $('status').textContent = `Reading ${data.name} · ${(data.read / 1048576).toFixed(1)} / ${(data.size / 1048576).toFixed(1)} MiB · ${data.count.toLocaleString()} lines indexed`;
    else if (data.kind === 'ready') {
      document.body.dataset.state = 'ready'; $('cancel').hidden = true;
      $('status').textContent = `Opened ${opened.length} local file${opened.length === 1 ? '' : 's'}. File order retained. No network access.`;
      currentStart = -1; renderFacts(); scheduleRender();
    } else if (data.kind === 'error') { $('status').textContent = data.message; $('cancel').hidden = true; document.body.dataset.state = 'error'; }
  };
}
function load(files: File[]) {
  if (!files.length) return;
  version++; opened = []; selected = undefined; currentStart = -1; currentFile = -1; rendering = false;
  resetWorker();
  $('welcome').hidden = true; $('facts').hidden = true; $('toolbar').hidden = true; $('cancel').hidden = false;
  $('status').textContent = `Reading ${files.length} local file${files.length === 1 ? '' : 's'}…`;
  rows.replaceChildren(); spacer.style.height = '0px'; $('sessions').replaceChildren();
  ($('detail') as HTMLDialogElement).close();
  document.body.dataset.state = 'loading';
  worker.postMessage({ kind: 'open', files });
}
for (const id of ['files', 'folder']) $(id).onchange = (event) => {
  const input = event.target as HTMLInputElement;
  const all = Array.from(input.files ?? []);
  // A directory can include native logs and documentation. Open JSONL files only.
  load(id === 'folder' ? all.filter(f => f.name.toLowerCase().endsWith('.jsonl')) : all);
  input.value = '';
};
$('cancel').onclick = () => {
  version++; worker.terminate(); $('cancel').hidden = true; document.body.dataset.state = 'cancelled';
  $('status').textContent = 'Loading cancelled. Reopen files to continue.';
};
let dragDepth = 0;
document.addEventListener('dragenter', e => { e.preventDefault(); dragDepth++; document.body.classList.add('dragging'); });
document.addEventListener('dragover', e => e.preventDefault());
document.addEventListener('dragleave', () => { if (--dragDepth <= 0) document.body.classList.remove('dragging'); });
async function droppedFiles(entry: any): Promise<File[]> {
  if (entry.isFile) return [await new Promise<File>((resolve, reject) => entry.file(resolve, reject))];
  const reader = entry.createReader(), result: File[] = [];
  while (true) {
    const batch: any[] = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
    if (!batch.length) return result;
    for (const item of batch) result.push(...await droppedFiles(item));
  }
}
document.addEventListener('drop', async e => {
  e.preventDefault(); dragDepth = 0; document.body.classList.remove('dragging');
  try {
    const entries = Array.from(e.dataTransfer?.items ?? []).map(i => i.webkitGetAsEntry?.()).filter(Boolean);
    const files: File[] = entries.length ? (await Promise.all(entries.map(droppedFiles))).flat() : Array.from(e.dataTransfer?.files ?? []);
    load(files.filter(f => f.name.toLowerCase().endsWith('.jsonl')));
  } catch { $('status').textContent = 'This folder could not be read. Use the file picker.'; }
});

function renderFiles() {
  $('file-count').textContent = String(opened.length);
  $('sessions').replaceChildren(...opened.map(f => {
    const b = button('', () => selectFile(f.id)); b.className = 'session'; b.dataset.file = String(f.id);
    b.setAttribute('aria-current', String(f.id === selected?.id));
    b.append(node('b', f.summary.header?.title ?? f.name), node('small', `${f.summary.header?.agent?.name ?? (f.unsupported ? 'Unsupported file' : 'ASR records')} · ${f.summary.count.toLocaleString()} lines`));
    return b;
  }));
}
function selectFile(id: number, at = 0) {
  selected = opened.find(f => f.id === id);
  if (!selected) return;
  version++; currentStart = -1; currentFile = -1;
  rows.replaceChildren();
  spacer.style.height = `${Math.min(8000000, selected.summary.count * rowHeight)}px`;
  $('toolbar').hidden = selected.summary.count === 0;
  $('record-count').textContent = `${selected.summary.count.toLocaleString()} lines · original order`;
  ($('line') as HTMLInputElement).max = String(selected.summary.count);
  renderFiles(); renderFacts(); jumpTo(at); scheduleRender();
}
function fact(title: string, value: unknown) {
  const e = node('div', undefined, 'fact');
  e.append(node('b', title), node('span', value === undefined ? 'unknown' : typeof value === 'string' ? value : JSON.stringify(value)));
  return e;
}
function annotationCurrent(file: OpenFile, at: number): boolean {
  const a = file.summary.annotations?.find(a => a.at === at);
  if (!a?.candidate) return false;
  if (a.kind === 'test' || a.kind === 'vcs') return true;
  return !opened.some(f => f.summary.annotations?.some(b => b.candidate && b.target === a.target && b.kind === a.kind && b.learnedAt > a.learnedAt));
}
function annotationLinks(root: HTMLElement, target: string, wholeSession = false) {
  for (const f of opened) for (const a of f.summary.annotations ?? []) {
    if ((wholeSession ? a.target.split('#')[0] === target : a.target === target) && annotationCurrent(f, a.at)) root.append(button(`Later ${a.kind}: ${a.target}`, () => selectFile(f.id, a.at)));
  }
}
function referenceLink(session: string, record?: string, kind = 'Related session'): HTMLElement {
  const matches = opened.filter(f => f.summary.reference === session);
  if (matches.length !== 1) return node('span', `${kind}: ${session}${record === undefined ? '' : '#' + record} (${matches.length ? 'ambiguous files' : 'unresolved, file not opened'})`, 'note unresolved');
  return button(`${kind}: ${session}${record === undefined ? '' : '#' + record}`, () => {
    const file = matches[0]; selectFile(file.id);
    if (record !== undefined) void rpc('find', { file: file.id, record }).then(({ at }) => {
      if (at === undefined) $('status').textContent = `Unresolved record reference: ${session}#${record}`;
      else jumpTo(at);
    }).catch(() => {});
  });
}
function renderFacts() {
  if (!selected) return;
  const root = $('facts'), { summary: s } = selected, h = s.header;
  root.hidden = false;
  root.replaceChildren(node('div', h ? 'SESSION OVERVIEW' : 'FILE OVERVIEW', 'eyebrow'), node('h1', h?.title ?? selected.name));
  if (selected.unsupported) { root.append(node('p', 'This is not an ASR JSONL file. Open a session file ending in .jsonl.', 'note')); return; }
  const facts = node('div', undefined, 'facts-grid');
  facts.append(fact('Session', s.reference), fact('Producer', h ? `${h.producer?.name ?? 'unknown'} · ${h.producer?.method ?? 'unknown'}` : 'unknown'), fact('Started', h?.startedAt), fact('Working directory', h?.cwd));
  root.append(facts);
  if (!h) root.append(node('p', 'No supported session header. Complete readable records remain in file order. Annotation files contain later facts, separate from session events.', 'note unresolved'));
  if (h?.endedAt !== undefined) root.append(fact('Ended (recorded)', h.endedAt));
  if (s.totals?.usage !== undefined || s.totals?.cost !== undefined) {
    const totals = node('details'); totals.append(node('summary', 'Latest reported session totals · separate from per-call sums'));
    if (s.totals.usage !== undefined) totals.append(fact('Usage (subagent scope unknown unless stated)', s.totals.usage));
    if (s.totals.cost !== undefined) totals.append(fact('Cost', s.totals.cost));
    root.append(totals);
  }
  root.append(node('div', s.missing.length ? `Declared losses: ${s.missing.join(', ')}` : 'Known losses: none declared. Capture completeness remains unknown.', 'losses'));
  if (s.issues) root.append(node('div', `${s.issues} reader diagnostic${s.issues === 1 ? '' : 's'}. Review marked lines in the timeline.`, 'note unresolved'));
  const relations = node('div', undefined, 'relations'), seen = new Set<string>();
  for (const r of s.relations) {
    const key = `${r.kind}|${r.session}|${r.record ?? ''}`;
    if (seen.has(key)) continue;
    seen.add(key); relations.append(referenceLink(r.session, r.record, r.kind));
  }
  for (const other of opened) if (s.reference && other.summary.header?.parent?.session === s.reference) {
    relations.append(referenceLink(other.summary.reference!, undefined, `child (${other.summary.header.parent.kind})`));
  }
  root.append(relations);
  const later = node('div', undefined, 'relations');
  if (s.reference) annotationLinks(later, s.reference, true);
  root.append(later);
  if (s.accounting.length) {
    const details = node('details'), table = node('table');
    details.append(node('summary', 'Model usage and cost · own calls only'));
    const heading = node('tr');
    for (const text of ['Model', 'Calls', 'Input tokens', 'Output tokens', 'Cost']) heading.append(node('th', text));
    table.append(heading);
    for (const a of s.accounting) {
      const tr = node('tr');
      const count = (total: string, known: number) => known ? `${total} (${known}/${a.calls} known)` : 'unknown';
      for (const text of [a.model, String(a.calls), count(a.input, a.inputKnown), count(a.output, a.outputKnown), Object.entries(a.costs).map(([currency, c]) => `${c.amount} ${currency} (${c.known}/${a.calls} known)`).join(', ') || 'unknown']) tr.append(node('td', text));
      table.append(tr);
    }
    details.append(table, node('p', 'Copied calls are excluded. Reported session totals stay on their update records. Cache and reasoning counts are included in input and output totals.', 'note'));
    root.append(details);
  }
}
function sections(root: HTMLElement, items: Section[], excerpt: boolean) {
  for (const s of excerpt ? items.slice(0, 4) : items) {
    root.append(node('div', s.title, 'section-label'));
    const text = excerpt ? s.text.slice(0, 3500) : s.text;
    const pre = node('pre');
    if (s.kind === 'diff') {
      pre.className = 'diff';
      for (const line of text.split('\n')) pre.append(node('span', line + '\n', line.startsWith('+') ? 'added' : line.startsWith('-') ? 'removed' : 'context'));
    } else pre.textContent = text;
    root.append(pre);
  }
}
function recordCard(v: View) {
  if (v.entry.type === 'annotation' && selected) {
    const text = annotationCurrent(selected, v.at) ? 'Current later fact. Separate from session actions.' : 'Historical or unfamiliar later fact. Original record retained.';
    v.sections = v.sections.map(s => s.title === 'Annotation status' ? { ...s, text } : s);
  }
  const e = v.entry, outer = node('article', undefined, 'record'), card = node('div', undefined, 'card');
  outer.dataset.type = e.type; outer.dataset.copy = String(e.copied); outer.dataset.record = e.id; outer.dataset.index = String(v.at);
  const head = node('div', undefined, 'record-head');
  head.append(node('span', e.type.replaceAll('_', ' '), 'tag'), node('span', `LINE ${e.line} · ${e.id}`), node('span', e.ts ?? 'time unknown'));
  if (e.copied) head.append(node('span', 'COPY', 'tag copy'));
  if (e.issue) head.append(node('span', 'READER DIAGNOSTIC', 'tag copy'));
  const content = node('div', undefined, 'record-content');
  sections(content, v.sections, true);
  if (e.truncated) content.append(node('p', 'Recorded text was shortened.', 'note unresolved'));
  const footer = node('div', undefined, 'record-footer');
  footer.append(button('Read record', () => void showDetail(v)));
  addLinks(footer, v);
  card.append(head, node('h3', e.title), content, footer); outer.append(card); return outer;
}
function addLinks(root: HTMLElement, v: View) {
  const jump = (text: string, at: number) => root.append(button(text, () => { ($('detail') as HTMLDialogElement).close(); jumpTo(at); currentStart = -1; scheduleRender(); }));
  if (v.pair) {
    root.append(node('span', v.pair.note, 'note'));
    if (v.pair.call !== undefined && v.pair.call !== v.at) jump('Call', v.pair.call);
    if (v.pair.result !== undefined && v.pair.result !== v.at) jump('Result', v.pair.result);
    for (const at of v.pair.approvals) if (at !== v.at) jump('Approval', at);
  }
  if (v.inference !== undefined) jump('Model call', v.inference);
  if (v.unresolved) root.append(node('span', v.unresolved, 'note unresolved'));
  for (const r of v.references) root.append(referenceLink(r.session, r.record, r.kind));
  if (selected?.summary.reference) annotationLinks(root, `${selected.summary.reference}#${encode(v.entry.id)}`);
  if (v.entry.callId && selected?.summary.reference) for (const f of opened) {
    const p = f.summary.header?.parent;
    if (p?.kind === 'subagent' && p.session === selected.summary.reference && p.callId === v.entry.callId) root.append(referenceLink(f.summary.reference!, undefined, 'subagent (child-side link)'));
  }
}
function scheduleRender() {
  if (scheduled) return;
  scheduled = true;
  requestAnimationFrame(() => { scheduled = false; void renderRows(); });
}
async function renderRows() {
  if (!selected || rendering || !selected.summary.count) return;
  const file = selected.id, stamp = version;
  const logical = logicalTop(), scrollTop = timeline.scrollTop;
  const start = Math.max(0, Math.floor(logical / rowHeight) - 2);
  if (start === currentStart && file === currentFile) { rows.style.top = `${scrollTop + start * rowHeight - logical}px`; return; }
  rendering = true;
  const end = Math.min(selected.summary.count, start + Math.ceil(timeline.clientHeight / rowHeight) + 6);
  try {
    const { views } = await rpc('range', { file, start, end });
    if (stamp !== version) return;
    rows.style.top = `${scrollTop + start * rowHeight - logical}px`; rows.replaceChildren(...views.map(recordCard));
    currentStart = start; currentFile = file;
  } catch { /* A new selection invalidates pending reads. */ }
  finally { rendering = false; if (stamp !== version || Math.max(0, Math.floor(logicalTop() / rowHeight) - 2) !== start) scheduleRender(); }
}
timeline.addEventListener('scroll', scheduleRender, { passive: true });
new ResizeObserver(scheduleRender).observe(timeline);
$('go').onclick = () => {
  if (!selected) return;
  const at = Math.min(selected.summary.count - 1, Math.max(0, Number(($('line') as HTMLInputElement).value) - 1));
  jumpTo(at);
};
async function showDetail(v: View) {
  if (!selected) return;
  const stamp = version;
  detailAt = v.at; detailFile = selected.id; rawPosition = 0;
  $('detail-title').textContent = v.entry.title;
  $('detail-body').replaceChildren(); sections($('detail-body'), v.sections, false); addLinks($('detail-body'), v);
  if (v.entry.copied) $('detail-body').prepend(node('p', 'Copied record. Excluded from this session’s cost and work credit.', 'note unresolved'));
  await showRaw();
  if (stamp !== version) return;
  if (!($('detail') as HTMLDialogElement).open) ($('detail') as HTMLDialogElement).showModal();
}
async function showRaw() {
  try {
    const file = detailFile, at = detailAt, offset = rawPosition;
    const raw = await rpc('raw', { file, at, offset });
    if (file !== detailFile || at !== detailAt || offset !== rawPosition) return;
    $('raw').textContent = raw.text;
    const previous = button('Previous page', () => { rawPosition = Math.max(0, rawPosition - 65536); void showRaw(); }); previous.disabled = !rawPosition;
    const next = button('Next page', () => { rawPosition += 65536; void showRaw(); }); next.disabled = !raw.next;
    $('raw-controls').replaceChildren(previous, node('span', `Bytes ${raw.offset.toLocaleString()}–${Math.min(raw.offset + 65536, raw.length).toLocaleString()} of ${raw.length.toLocaleString()}`), next);
  } catch { $('raw').textContent = 'Original record unavailable.'; }
}
$('close-detail').onclick = () => ($('detail') as HTMLDialogElement).close();
document.body.dataset.state = 'empty';
