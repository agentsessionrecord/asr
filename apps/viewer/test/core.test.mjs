import assert from 'node:assert/strict';
import test from 'node:test';
import { SessionIndex, readLines, parseRecord, format, updateSettings, addDecimal, sectionsFor, resolveAnnotations, sessionRef, compareStates, RECORD_LIMIT } from '../dist/core.mjs';

const header = { type: 'session', id: 'header', formatVersion: '0.1', agent: { name: 'com.example.agent' }, sessionId: 'test', producer: { name: 'fixture', version: '1', method: 'native' } };
async function index(records, tail = '') {
  const file = new Blob([records.map(r => typeof r === 'string' ? r : JSON.stringify(r)).join('\n') + '\n' + tail]);
  const result = new SessionIndex();
  for await (const line of readLines(file, 23)) result.append(line);
  return { index: result, summary: result.finish() };
}
const call = (id, callId = 'call') => ({ type: 'tool_call', id, callId, name: 'shell' });
const result = (id, callId = 'call') => ({ type: 'tool_result', id, callId, status: 'completed' });
const approval = (id, callId = 'call') => ({ type: 'approval', id, callId, decision: 'approved' });

test('index capacity fails explicitly before retaining another entry', () => {
  const result = new SessionIndex(2);
  const line = n => ({ start: n * 10, length: 9, line: n + 1, text: JSON.stringify({ ...header, id: `r-${n}` }) });
  result.append(line(0)); result.append(line(1));
  assert.throws(() => result.append(line(2)), /capacity/);
  assert.equal(result.entries.length, 2);
});

test('keeps file order with backwards timestamps and links a forward result', async () => {
  const { index: i } = await index([header, { ...call('c'), ts: '2030-01-01T00:00:02Z' }, { type: 'message', id: 'm', role: 'user', content: [], ts: '2030-01-01T00:00:01Z' }, approval('a'), result('r')]);
  assert.deepEqual(i.entries.map(e => e.id), ['header', 'c', 'm', 'a', 'r']);
  assert.deepEqual(i.pair(1), { call: 1, result: 4, approvals: [3], note: 'Paired by unique call ID.' });
});
test('accepts results before calls without guessing by proximity', async () => {
  const { index: i } = await index([header, result('r'), call('c')]);
  assert.equal(i.pair(1).call, 2);
});
test('duplicate calls invalidate results, approvals and effects across the entire file', async () => {
  const { index: i } = await index([header, call('c1'), result('r'), approval('a1'), call('c2')]);
  for (const at of [1, 2, 3, 4]) {
    assert.equal(i.pair(at).call, undefined);
    assert.equal(i.pair(at).result, undefined);
    assert.deepEqual(i.pair(at).approvals, []);
  }
});
test('keeps repeated decisions and refuses to choose between duplicate results', async () => {
  const { index: i } = await index([header, call('c'), approval('a1'), approval('a2'), result('r1'), result('r2')]);
  assert.deepEqual(i.pair(1).approvals, [2, 3]);
  assert.equal(i.pair(1).result, undefined);
  assert.match(i.pair(1).note, /Multiple results/);
});
test('missing results leave outcomes unknown, absent call IDs stay unpaired', async () => {
  const { index: i } = await index([header, call('c'), { type: 'tool_result', id: 'orphan', status: 'completed' }]);
  assert.match(i.pair(1).note, /unknown/);
  assert.match(i.pair(2).note, /Unpaired/);
});
test('stream framing survives UTF-8 and LF boundaries, malformed lines and an incomplete tail', async () => {
  const { index: i } = await index([header, '{broken', { type: 'message', id: 'm', role: 'user', content: [{ type: 'text', text: '雪🙂\ntext' }] }], JSON.stringify(call('incomplete')));
  assert.deepEqual(i.entries.map(e => e.type), ['session', 'diagnostic', 'message', 'diagnostic']);
  assert.match(i.entries[3].issue, /Incomplete/);
  assert.equal(i.groups.size, 0);
});
test('invalid UTF-8 is diagnosed and following records survive', async () => {
  const blob = new Blob([new Uint8Array([0xff, 10]), JSON.stringify(header), '\n']);
  const i = new SessionIndex();
  for await (const line of readLines(blob, 5)) i.append(line);
  assert.match(i.entries[0].issue, /UTF-8/);
  assert.equal(i.entries[1].type, 'session');
});
test('oversized lines are bounded and retain byte offsets for inspection', async () => {
  const blob = new Blob(['x'.repeat(RECORD_LIMIT + 1), '\n', JSON.stringify(header), '\n']);
  const lines = [];
  for await (const line of readLines(blob)) lines.push(line);
  assert.equal(lines[0].text, undefined);
  assert.match(lines[0].issue, /decode limit/);
  assert.equal(lines[1].start, RECORD_LIMIT + 2);
  assert.equal(parseRecord(lines[1].text).id, 'header');
});
test('preserves numeric lexemes, unsafe integers, negative zero and exponents', () => {
  const r = parseRecord('{"type":"tool_call","id":"n","callId":"c","input":{"n":9007199254740993,"d":1.23000000000000001,"e":1e+30,"z":-0}}');
  assert.match(format(r), /9007199254740993/);
  assert.match(format(r), /1\.23000000000000001/);
  assert.match(format(r), /1e\+30/);
  assert.match(format(r), /"z": -0/);
  assert.match(sectionsFor(r)[0].text, /9007199254740993/);
});
test('rejects duplicate keys at every depth including escaped keys', () => {
  for (const text of ['{"type":"message","id":"a","id":"b"}', '{"type":"tool_call","id":"a","input":{"a":1,"\\u0061":2}}']) assert.throws(() => parseRecord(text), /Duplicate/);
});
test('settings retain omitted fields, clear nulls, replace boundaries, and invalidate asks only on changes', () => {
  const original = { mode: 'plan', approval: 'ask', asks: 'always', externalSandbox: { kind: 'container', source: 'setting' }, modelSettings: { temperature: 0, reasoningEffort: 'high' } };
  assert.equal(updateSettings(original, { mode: 'plan' }).asks, 'always');
  const next = updateSettings(original, { mode: 'execute', modelSettings: { reasoningEffort: null }, externalSandbox: {} });
  assert.equal(next.asks, undefined);
  assert.equal(next.approval, 'ask');
  assert.equal(next.modelSettings.temperature, 0);
  assert.equal(next.modelSettings.reasoningEffort, undefined);
  assert.deepEqual(next.externalSandbox, {});
  assert.equal(updateSettings(next, { modelSettings: null }).modelSettings, undefined);
  assert.equal(original.mode, 'plan');
});
test('missing losses are a union and empty updates never remove them', async () => {
  const { summary } = await index([{ ...header, missing: ['approvals'] }, { type: 'session_info', id: 'a', missing: ['tools'] }, { type: 'session_info', id: 'b', missing: [] }]);
  assert.deepEqual(summary.missing, ['approvals', 'tools']);
});
test('session updates retain omitted facts, add repositories, replace totals and replace whole tool lists', async () => {
  const { index: i, summary } = await index([{ ...header, title: 'initial', repos: [{ path: '/work/a' }] },
    { type: 'session_info', id: 'a', title: 'latest', endedAt: '2030-01-01T00:00:00Z', usage: { inputTokens: 10, outputTokens: 2 }, repos: [{ path: '/work/b' }], tools: [{ name: 'shell' }] },
    { type: 'session_info', id: 'b', usage: { inputTokens: 20 }, tools: [] },
    { type: 'session_info', id: 'c', cost: { amount: 0, currency: 'USD' } }]);
  assert.equal(summary.header.title, 'latest');
  assert.equal(summary.header.endedAt, '2030-01-01T00:00:00Z');
  assert.equal(summary.header.repos.length, 2);
  assert.equal(summary.totals.usage, '{"inputTokens": 20}');
  assert.deepEqual(i.tools, []);
});
test('copied prefix follows file order, copiedFrom is excluded, new child inference is counted', async () => {
  const inference = (id, amount) => ({ type: 'inference', id, model: { id: 'served', requested: 'alias' }, usage: { inputTokens: 10, outputTokens: 0 }, cost: { amount, currency: 'USD' } });
  const { index: i, summary } = await index([{ ...header, parent: { session: 'com.example.agent:parent', kind: 'fork', copiedThrough: 'z' } }, inference('z', 9), { ...inference('copy', 8), copiedFrom: { record: 'upstream' } }, inference('own', 0.1), inference('own2', 0.2), { type: 'session_info', id: 'totals', usage: { inputTokens: 200 }, cost: { amount: 10, currency: 'USD' } }]);
  assert.deepEqual(i.entries.map(e => e.copied), [false, true, true, false, false, false]);
  assert.equal(summary.accounting[0].calls, 2);
  assert.equal(summary.accounting[0].input, '20');
  assert.equal(summary.accounting[0].output, '0');
  assert.equal(summary.accounting[0].costs.USD.amount, '0.3');
});
test('unknown accounting stays unknown and currencies stay separate', async () => {
  const { summary } = await index([header, { type: 'inference', id: 'i', model: { requested: 'alias' } }, { type: 'inference', id: 'j', model: { requested: 'alias' }, cost: { amount: 0, currency: 'EUR' } }]);
  assert.equal(summary.accounting[0].inputKnown, 0);
  assert.equal(summary.accounting[0].costs.EUR.known, 1);
  assert.equal(summary.accounting[0].costs.EUR.amount, '0');
});
test('uses exact decimal accounting without binary rounding', () => {
  assert.equal(addDecimal('0.1', '0.2'), '0.3');
  assert.equal(addDecimal('1e3', '0.001'), '1000.001');
  assert.equal(addDecimal('9007199254740993', '1'), '9007199254740994');
  assert.equal(addDecimal('0', '-0.1'), '-0.1');
});
test('preserves false, zero, empty input, effective input, and empty tool lists', () => {
  for (const input of [false, 0, '', null]) assert.equal(sectionsFor({ ...result('r'), input })[0].text, typeof input === 'string' ? '' : JSON.stringify(input));
  assert.equal(sectionsFor({ type: 'session_info', id: 's', tools: [] })[0].text, '[]');
});
test('unknown parts do not hide known parts and encrypted reasoning is not displayed', () => {
  const sections = sectionsFor({ type: 'message', id: 'm', role: 'user', content: [{ type: 'future', text: 'unknown' }, { type: 'text', text: 'known', author: 'hook', origin: 'injected' }, { type: 'reasoning', visibility: 'encrypted', text: 'never render' }] });
  assert.equal(sections.length, 2);
  assert.match(sections[0].title, /hook.*injected/);
  assert.equal(sections[1].text, 'Content unavailable');
});
test('resolves annotation corrections before timestamps and retains additive facts and tied values', () => {
  const a = (id, kind, at, extra = {}) => ({ type: 'annotation', id, kind, at, session: 'com.example.agent:test', source: { name: 'test' }, data: {}, ...extra });
  const annotations = [a('old', 'title', '2030-01-03T00:00:00Z'), a('correct', 'title', '2030-01-01T00:00:00Z', { supersedes: 'old' }), a('test1', 'test', '2030-01-01T00:00:00Z'), a('test2', 'test', '2030-01-02T00:00:00Z'), a('tied', 'title', '2030-01-01T00:00:00Z')];
  assert.deepEqual([...resolveAnnotations(annotations)], ['correct', 'test1', 'test2', 'tied']);
});
test('annotation ordering retains submillisecond precision across time zones', () => {
  const a = { type: 'annotation', id: 'a', kind: 'title', session: 'com.example.agent:test', source: { name: 'test' }, data: {} };
  assert.deepEqual([...resolveAnnotations([{ ...a, at: '2030-01-01T00:00:00.000001Z' }, { ...a, id: 'b', at: '2030-01-01T01:00:00.000002+01:00' }])], ['b']);
});
test('builds session references without treating encoded separators as structure', () => {
  assert.equal(sessionRef({ ...header, namespace: 'box:7', sessionId: 'run %#雪' }), 'com.example.agent:box%3A7:run%20%25%23雪');
});
test('diff views distinguish recorded patches, snippets and comparisons of full states', () => {
  assert.equal(sectionsFor({ type: 'file_change', id: 'f', op: 'modify', status: 'applied', path: 'a', patch: '--- a\n+++ a\n-x\n+y\n' }).find(s => s.kind === 'diff').text, '--- a\n+++ a\n-x\n+y\n');
  assert.match(compareStates('same\nold\nend', 'same\nnew\nend'), /-old\n\+new/);
  assert.doesNotMatch(compareStates('same\nold\nend', 'same\nnew\nend'), /-same|\+end/);
});
