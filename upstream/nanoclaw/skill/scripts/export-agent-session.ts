import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';

type Row = Record<string, unknown>;
function object(value: unknown): Row {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as Row) : {};
}

function validTimestamp(value: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-](\d{2}):(\d{2}))$/.exec(value);
  if (!match) return false;
  const [, year, month, day, hour, minute, second, , offsetHour, offsetMinute] = match;
  const days = new Date(Date.UTC(Number(year), Number(month), 0)).getUTCDate();
  return (
    Number(month) >= 1 &&
    Number(month) <= 12 &&
    Number(day) >= 1 &&
    Number(day) <= days &&
    Number(hour) < 24 &&
    Number(minute) < 60 &&
    Number(second) < 60 &&
    Number(offsetHour ?? 0) < 24 &&
    Number(offsetMinute ?? 0) < 60 &&
    Number.isFinite(Date.parse(value))
  );
}

// Provider transcripts are untrusted input. Exclude known credential fields and tokens at export.
function clean(value: unknown): unknown {
  if (typeof value === 'string')
    return value.replace(
      /\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b/g,
      '[redacted]',
    );
  if (Array.isArray(value)) return value.map(clean);
  if (value !== null && typeof value === 'object')
    return Object.fromEntries(
      Object.entries(value)
        .filter(
          ([key]) =>
            !/^(?:api[_-]?key|authorization|password|access[_-]?token|refresh[_-]?token|credentials|signature|thinkingSignature)$/i.test(
              key,
            ),
        )
        .map(([key, item]) => [key, clean(item)]),
    );
  return value;
}

/** Export one explicitly associated Claude SDK transcript in its native file order. */
export function exportAgentSession(source: string, sessionId: string): string {
  if (!sessionId) throw new Error('A NanoClaw session ID is required');
  const rows: Row[] = [
    {
      type: 'session',
      id: 'header',
      formatVersion: '0.1',
      agent: { name: 'nanoclaw' },
      sessionId,
      producer: { name: 'nanoclaw-agent-session', version: '0.2.0', method: 'native', source: 'claude-sdk-transcript' },
      missing: [
        'history',
        'approvals',
        'agent_settings',
        'tools',
        'file_changes',
        'commits',
        'subagents',
        'copies',
        'reasoning',
        'media',
        'provider_state',
        'message_author',
        'redacted_fields',
        'timestamps',
        'usage',
        'model',
        'mailbox_delivery',
      ],
    },
    {
      type: 'gap',
      id: 'continuation-prefix',
      reason: 'not_recorded',
      detail:
        'Only the selected Claude provider continuation is exported. Mailbox delivery and other continuations are not read.',
    },
  ];
  const used = new Set(['header', 'continuation-prefix']);
  const responses = new Map<string, string>();
  const nativeIds = new Set<string>();
  const results = new Set<string>();
  const append = (value: Row, preferred: string, timestamp: unknown): void => {
    let id = preferred;
    if (
      !id ||
      id.length > 240 ||
      [...id].some(
        (character) =>
          character.codePointAt(0)! < 32 || (character.codePointAt(0)! >= 127 && character.codePointAt(0)! <= 159),
      ) ||
      used.has(id)
    )
      id = `derived-${rows.length}`;
    while (used.has(id)) id += '-derived';
    used.add(id);
    if (typeof timestamp === 'string' && validTimestamp(timestamp)) value.ts = timestamp;
    rows.push({ id, ...value });
  };
  const lines = source.split('\n');
  if (lines.at(-1) === '') lines.pop();
  const parsed = lines.map((line, position): Row | undefined => {
    try {
      if (position === lines.length - 1 && !source.endsWith('\n')) throw new SyntaxError('Incomplete tail');
      return object(
        JSON.parse(line, (_key: string, value: unknown, context?: { source: string }) => {
          if (typeof value === 'number' && Number.isInteger(value) && !Number.isSafeInteger(value)) {
            if (!context) throw new Error('Lossless JSON parsing is unavailable');
            return context.source;
          }
          return value;
        }),
      );
    } catch (error) {
      if (!(error instanceof SyntaxError)) throw error;
      return undefined;
    }
  });
  // SDK rows can carry separate content blocks for one provider response. Usage snapshots replace fields.
  const responseEvidence = new Map<string, Row>();
  for (const native of parsed) {
    if (!native || native.type !== 'assistant') continue;
    const message = object(native.message);
    if (typeof message.id !== 'string' || !message.id) continue;
    const previous = responseEvidence.get(message.id) ?? {};
    if (previous.model && message.model && previous.model !== message.model)
      throw new Error('Conflicting provider models for one response');
    responseEvidence.set(message.id, {
      ...previous,
      ...message,
      usage: { ...object(previous.usage), ...object(message.usage) },
    });
  }
  let providerSession: string | undefined;
  for (const [position, native] of parsed.entries()) {
    if (!native) {
      append({ type: 'gap', reason: 'unparseable', count: 1 }, `line-${position}`, undefined);
      continue;
    }
    if (typeof native.uuid === 'string') {
      if (nativeIds.has(native.uuid)) throw new Error('Duplicate native record identity');
      nativeIds.add(native.uuid);
    }
    if (typeof native.sessionId === 'string') {
      if (providerSession && providerSession !== native.sessionId)
        throw new Error('Select a transcript from one provider session');
      providerSession = native.sessionId;
    }
    const message = object(native.message);
    const id = typeof native.uuid === 'string' ? native.uuid : `line-${position}`;
    if (native.type !== 'user' && native.type !== 'assistant') {
      append(
        { type: 'gap', reason: 'not_recorded', count: 1, detail: 'Unsupported provider transcript record.' },
        id,
        native.timestamp,
      );
      continue;
    }
    let inferenceId: string | undefined;
    if (native.type === 'assistant' && typeof message.id === 'string' && message.id) {
      inferenceId = responses.get(message.id);
      if (!inferenceId) {
        const evidence = responseEvidence.get(message.id)!;
        const call: Row = { type: 'inference', _meta: { 'dev.nanoclaw.export': { responseId: message.id } } };
        if (typeof evidence.model === 'string' && evidence.model) call.model = { id: evidence.model };
        if (typeof evidence.stop_reason === 'string') call.stopReason = evidence.stop_reason;
        const usage = object(evidence.usage);
        const count = (value: unknown): value is number =>
          typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
        const normalized: Row = {};
        if (
          count(usage.input_tokens) &&
          ['cache_read_input_tokens', 'cache_creation_input_tokens'].every(
            (key) => usage[key] === undefined || count(usage[key]),
          )
        ) {
          const total =
            usage.input_tokens +
            (count(usage.cache_read_input_tokens) ? usage.cache_read_input_tokens : 0) +
            (count(usage.cache_creation_input_tokens) ? usage.cache_creation_input_tokens : 0);
          if (count(total)) normalized.inputTokens = total;
        }
        for (const [target, key] of [
          ['outputTokens', 'output_tokens'],
          ['cacheReadTokens', 'cache_read_input_tokens'],
          ['cacheWriteTokens', 'cache_creation_input_tokens'],
        ])
          if (count(usage[key])) normalized[target] = usage[key];
        if (Object.keys(normalized).length) call.usage = normalized;
        const exactCounts = Object.fromEntries(
          Object.entries(usage).filter(([, value]) => typeof value === 'string' && /^-?[0-9]+$/.test(value)),
        );
        if (Object.keys(exactCounts).length)
          object(object(call._meta)['dev.nanoclaw.export']).exactCounts = exactCounts;
        append(call, `inference-${message.id}`, native.timestamp);
        inferenceId = rows.at(-1)!.id as string;
        responses.set(message.id, inferenceId);
      }
    }
    const blocks = typeof message.content === 'string' ? [{ type: 'text', text: message.content }] : message.content;
    if (!Array.isArray(blocks)) {
      append({ type: 'gap', reason: 'unparseable', count: 1 }, id, native.timestamp);
      continue;
    }
    for (const [index, value] of blocks.entries()) {
      const block = object(value);
      let record: Row;
      if (block.type === 'tool_use' && typeof block.id === 'string' && typeof block.name === 'string') {
        record = {
          type: 'tool_call',
          callId: block.id,
          name: block.name,
          requestedBy: 'model',
          ...(inferenceId ? { inferenceId } : {}),
          ...(Object.hasOwn(block, 'input') ? { input: clean(block.input) } : {}),
        };
      } else if (block.type === 'tool_result' && typeof block.tool_use_id === 'string') {
        if (results.has(block.tool_use_id)) throw new Error('Duplicate tool result in transcript');
        results.add(block.tool_use_id);
        const content =
          typeof block.content === 'string'
            ? [{ type: 'text', text: clean(block.content) }]
            : Array.isArray(block.content)
              ? block.content
                  .map(object)
                  .filter((part) => part.type === 'text' && typeof part.text === 'string')
                  .map((part) => ({ type: 'text', text: clean(part.text) }))
              : undefined;
        record = {
          type: 'tool_result',
          callId: block.tool_use_id,
          status: block.is_error === true ? 'failed' : block.is_error === false ? 'completed' : 'unknown',
          ...(content ? { content } : {}),
        };
      } else if (block.type === 'text' && typeof block.text === 'string') {
        record = {
          type: 'message',
          role: native.type,
          content: [{ type: 'text', text: clean(block.text) }],
          ...(inferenceId ? { inferenceId, author: 'model' } : {}),
        };
      } else if (block.type === 'thinking' || block.type === 'redacted_thinking') {
        record = {
          type: 'message',
          role: 'assistant',
          content: [
            block.type === 'redacted_thinking'
              ? { type: 'reasoning', visibility: 'encrypted' }
              : {
                  type: 'reasoning',
                  visibility: typeof block.thinking === 'string' && block.thinking ? 'summary' : 'omitted',
                  ...(typeof block.thinking === 'string' && block.thinking ? { summary: [clean(block.thinking)] } : {}),
                },
          ],
          ...(inferenceId ? { inferenceId } : {}),
        };
      } else {
        record = { type: 'gap', reason: 'not_recorded', count: 1, detail: 'Unsupported provider content block.' };
      }
      if (
        JSON.stringify(clean(block)) !== JSON.stringify(block) ||
        (record.type === 'tool_result' &&
          Array.isArray(block.content) &&
          block.content.some((part) => object(part).type !== 'text'))
      )
        record.truncated = true;
      append(record, `${id}/${index}`, native.timestamp);
    }
  }
  return rows.map((row) => JSON.stringify(row)).join('\n') + '\n';
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const { values } = parseArgs({
      options: { session: { type: 'string' }, transcript: { type: 'string' }, format: { type: 'string' } },
    });
    if (!values.session || !values.transcript || values.format !== 'agent-session')
      throw new Error('Use --session ID --transcript FILE --format agent-session');
    process.stdout.write(exportAgentSession(readFileSync(values.transcript, 'utf8'), values.session));
  } catch (error) {
    if (!(error instanceof Error)) throw error;
    console.error(error.message);
    process.exitCode = 1;
  }
}
