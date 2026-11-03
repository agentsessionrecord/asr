import { SessionIndex, readLines, parseRecord, sectionsFor, RAW_PAGE, INDEX_LIMIT, type View, type ASRRecord } from './core';

const scope = self as unknown as { onmessage: ((e: MessageEvent) => void) | null; postMessage: (data: unknown) => void };
const files = new Map<number, { file: File; index: SessionIndex }>();
let generation = 0;

async function record(fileId: number, at: number): Promise<ASRRecord | undefined> {
  const item = files.get(fileId)!;
  const entry = item.index.entries[at];
  if (!entry || entry.issue) return undefined;
  try { return parseRecord(await item.file.slice(entry.start, entry.start + entry.length).text()); }
  catch { return undefined; }
}

async function view(fileId: number, at: number): Promise<View> {
  const { index } = files.get(fileId)!, entry = index.entries[at];
  const r = await record(fileId, at);
  const result: View = { at, entry, sections: r ? sectionsFor(r) : [{ title: 'Reader diagnostic', text: entry.issue ?? 'Record unavailable' }], references: [...entry.references] };
  if (entry.settingsAfter !== undefined) result.sections.push({ title: 'Recorded settings now in effect (cleared fields are unknown)', text: entry.settingsAfter });
  if (entry.annotationState) result.sections.unshift({ title: 'Annotation status', text: entry.annotationState });
  if (['tool_call', 'tool_result', 'approval', 'file_change', 'vcs'].includes(entry.type) && (entry.callId !== undefined || ['tool_result', 'approval'].includes(entry.type))) {
    result.pair = index.pair(at);
    if (result.pair.approvals.length > 12) {
      result.pair.note += ` ${result.pair.approvals.length} approval records. First 12 linked here. All remain in the timeline.`;
      result.pair.approvals = result.pair.approvals.slice(0, 12);
    }
    if (entry.type === 'tool_call' && result.pair.result !== undefined) {
      const effective = await record(fileId, result.pair.result);
      if (effective) {
        for (const section of sectionsFor(effective).filter(s => s.title === 'Effective input learned at completion')) result.sections.unshift(section);
        result.sections.unshift({ title: 'Recorded outcome', text: String(effective.status ?? 'unknown') });
      }
    }
  }
  if (entry.inferenceId !== undefined) {
    const matches = index.ids.get(entry.inferenceId);
    if (matches?.length === 1 && index.entries[matches[0]].type === 'inference') result.inference = matches[0];
    else result.unresolved = `Unresolved model call: ${entry.inferenceId}`;
  }
  if (entry.copied && index.header?.parent && !entry.copiedFrom) result.references.push({ session: index.header.parent.session, kind: 'copied prefix source' });
  if (entry.copiedFrom?.record && !entry.copiedFrom.session) result.unresolved = `${result.unresolved ?? ''} Copy source record unresolved: ${entry.copiedFrom.record}`;
  // Bound structured messages and DOM text. Original bytes remain pageable.
  let budget = 60000;
  result.sections = result.sections.slice(0, 100).map(s => {
    const available = Math.max(0, Math.min(20000, budget));
    budget -= Math.min(available, s.text.length);
    return { ...s, text: s.text.length > available ? s.text.slice(0, available) + '\n[Display excerpt. Inspect original record for all bytes.]' : s.text };
  });
  return result;
}

scope.onmessage = async ({ data }) => {
  const { request, kind } = data;
  try {
    if (kind === 'open') {
      const current = ++generation;
      files.clear();
      if (data.files.length > 64) throw new Error('File capacity');
      let indexed = 0;
      for (let id = 0; id < data.files.length; id++) {
        const file: File = data.files[id], index = new SessionIndex();
        files.set(id, { file, index });
        if (!file.name.toLowerCase().endsWith('.jsonl')) {
          scope.postMessage({ kind: 'file', id, name: file.webkitRelativePath || file.name, unsupported: true, summary: { count: 0, missing: [], issues: 0, relations: [], accounting: [] } });
          continue;
        }
        let progress = 0;
        for await (const line of readLines(file)) {
          if (current !== generation) return;
          if (++indexed > INDEX_LIMIT) throw new Error('Index capacity');
          index.append(line);
          if (line.start - progress > 4 * 1024 * 1024) {
            progress = line.start;
            scope.postMessage({ kind: 'progress', name: file.name, read: line.start, size: file.size, count: index.entries.length });
          }
        }
        scope.postMessage({ kind: 'file', id, name: file.webkitRelativePath || file.name, summary: index.finish() });
      }
      scope.postMessage({ kind: 'ready' });
    } else if (kind === 'range') {
      const { index } = files.get(data.file)!;
      const views: View[] = [];
      for (let at = data.start; at < Math.min(index.entries.length, data.end); at++) views.push(await view(data.file, at));
      scope.postMessage({ request, views });
    } else if (kind === 'find') {
      const { index } = files.get(data.file)!;
      const matches = index.ids.get(data.record);
      scope.postMessage({ request, at: matches?.length === 1 ? matches[0] : undefined });
    } else if (kind === 'raw') {
      const { file, index } = files.get(data.file)!, e = index.entries[data.at];
      const offset = Math.max(0, Math.min(e.length, data.offset));
      const text = await file.slice(e.start + offset, e.start + Math.min(e.length, offset + RAW_PAGE)).text();
      scope.postMessage({ request, text, offset, length: e.length, next: offset + RAW_PAGE < e.length });
    }
  } catch {
    scope.postMessage({ request, kind: 'error', message: 'Unable to read these files. Open at most 64 files and 250,000 lines. Use a browser with JSON source context support.' });
  }
};
