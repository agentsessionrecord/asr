import { expect, test } from 'vitest';
import { exportAgentSession } from './export-agent-session.js';

const source =
  [
    {
      type: 'user',
      uuid: 'u',
      sessionId: 'continuation',
      timestamp: '2026-01-02T00:00:00Z',
      message: { role: 'user', content: 'Exact\r\n' },
    },
    {
      type: 'assistant',
      uuid: 'a',
      sessionId: 'continuation',
      timestamp: '2026-01-01T00:00:00Z',
      message: {
        id: 'response-1',
        model: 'served',
        usage: { input_tokens: 10, cache_read_input_tokens: 2, cache_creation_input_tokens: 3, output_tokens: 0 },
        content: [
          { type: 'thinking', thinking: 'Inspect the fixture.', signature: 'excluded-synthetic-value' },
          {
            type: 'tool_use',
            id: 'call-1',
            name: 'Read',
            input: { path: '/work/fixture', credentials: 'excluded-synthetic-value' },
          },
        ],
      },
    },
    {
      type: 'user',
      uuid: 'r',
      sessionId: 'continuation',
      message: { content: [{ type: 'tool_result', tool_use_id: 'call-1', is_error: false, content: 'done\n' }] },
    },
  ]
    .map((row) => JSON.stringify(row))
    .join('\n') + '\n';

test('exports provider response boundaries and tool calls without guessing mailbox order', () => {
  const output = exportAgentSession(source, 'synthetic-session');
  const records = output
    .trimEnd()
    .split('\n')
    .map((line) => JSON.parse(line));
  expect(records[2].content[0].text).toBe('Exact\r\n');
  expect(records[2].author).toBeUndefined();
  const inference = records.find((row) => row.type === 'inference');
  expect(inference.model).toEqual({ id: 'served' });
  expect(inference.usage).toMatchObject({ inputTokens: 15, outputTokens: 0 });
  expect(records.find((row) => row.type === 'tool_call').inferenceId).toBe(inference.id);
  expect(records.find((row) => row.type === 'tool_result').status).toBe('completed');
  expect(output).not.toContain('excluded-synthetic-value');
  expect(output).not.toContain('endedAt');
  expect(output).toBe(exportAgentSession(source, 'synthetic-session'));
  expect(records[2].ts > inference.ts).toBe(true);
});

test('marks corruption and refuses mixed provider sessions or duplicate records', () => {
  expect(JSON.parse(exportAgentSession('bad\n{', 'synthetic').split('\n')[2]).reason).toBe('unparseable');
  expect(() => exportAgentSession(source + source, 'synthetic')).toThrow('Duplicate');
  expect(() => exportAgentSession(source + JSON.stringify({ sessionId: 'other' }) + '\n', 'synthetic')).toThrow(
    'one provider session',
  );
});

test('folds split response blocks and final usage without summing snapshots', () => {
  const native = source
    .trimEnd()
    .split('\n')
    .map((line) => JSON.parse(line));
  const reply = native[1];
  const split = {
    ...reply,
    uuid: 'a-final',
    message: { ...reply.message, usage: { output_tokens: 4 }, content: [reply.message.content[1]] },
  };
  reply.message.content = [reply.message.content[0]];
  const records = exportAgentSession(
    [native[0], reply, split, native[2]].map((row) => JSON.stringify(row)).join('\n') + '\n',
    'synthetic',
  )
    .trimEnd()
    .split('\n')
    .map((line) => JSON.parse(line));
  const calls = records.filter((row) => row.type === 'inference');
  expect(calls).toHaveLength(1);
  expect(calls[0].usage).toMatchObject({ inputTokens: 15, outputTokens: 4 });
  expect(records.find((row) => row.type === 'tool_call').inferenceId).toBe(calls[0].id);
});

test('keeps unsafe cache counts exact and omits an invalid inclusive total or date', () => {
  const input = source
    .replace('"cache_read_input_tokens":2', '"cache_read_input_tokens":9007199254740993')
    .replace('2026-01-02T00:00:00Z', '2026-02-30T00:00:00Z');
  const records = exportAgentSession(input, 'synthetic')
    .trimEnd()
    .split('\n')
    .map((line) => JSON.parse(line));
  const inference = records.find((row) => row.type === 'inference');
  expect(inference.usage.inputTokens).toBeUndefined();
  expect(inference._meta['dev.nanoclaw.export'].exactCounts.cache_read_input_tokens).toBe('9007199254740993');
  expect(records[2].ts).toBeUndefined();
});
