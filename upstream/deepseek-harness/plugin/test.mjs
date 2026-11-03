import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Context, Service } from '@deepseek-ai/cordis';
import { HostConnectionService } from '@deepseek-ai/dsh-client-connection';
import * as plugin from './dist/index.js';

const snapshot = {
  session: { id: 'synthetic', createdAt: 1790985600000 }, inheritedEventCount: 0,
  events: [
    { seq: 0, time: 1790985600000, type: 'user/message', data: { source: { kind: 'user' }, content: [{ type: 'text', text: 'Exact\r\n' }] } },
    { seq: 1, time: 1790985600001, type: 'tool/call', data: { callId: 'c', name: 'read', arguments: '{"n":9007199254740993}' } },
    { seq: 2, time: 1790985600002, type: 'tool/result', data: { message: { source: { callId: 'c' }, isError: false, content: [{ type: 'text', text: 'old' }] } } },
    { seq: 3, time: 1790985600003, type: 'user/message', data: { source: { kind: 'user' }, content: [{ type: 'text', text: 'Between' }] } },
    { seq: 4, time: 1790985600004, type: 'tool/result', data: { message: { source: { callId: 'c' }, isError: true, content: [{ type: 'text', text: 'new' }] } } },
  ],
};

test('exports the final result at completion without rounding arguments', () => {
  const text = plugin.formatAgentSession(snapshot.session, snapshot.events, 0);
  const rows = text.trimEnd().split('\n').map(JSON.parse);
  assert.equal(rows[1].content[0].text, 'Exact\r\n');
  assert.equal(rows[1].author, undefined);
  assert.equal(rows.find(row => row.type === 'tool_call').input.n, '9007199254740993');
  assert.equal(rows.filter(row => row.type === 'tool_result').length, 1);
  assert.equal(rows.at(-1).status, 'failed');
  assert.ok(text.indexOf('Between') < text.indexOf('"text":"new"'));
  assert.equal(plugin.formatAgentSession(snapshot.session, snapshot.events, 0), text);
  assert.ok(!plugin.formatAgentSession(snapshot.session, snapshot.events, snapshot.events.length).includes('Exact'));
});

test('Cordis mounts and removes the route and keeps read failures opaque', async () => {
  const context = new Context();
  const routes = new Map();
  let failure;
  class Connection extends Service {
    constructor() { super(context, 'connection'); }
    fetch = { register(value) { routes.set(value.path, value); return async () => { routes.delete(value.path); }; } };
  }
  class Query extends Service {
    constructor() { super(context, 'sessionQuery'); }
    async readSession() { if (failure) throw failure; return snapshot; }
  }
  new Connection(); new Query();
  await context.plugin(plugin);
  const route = routes.get(plugin.route);
  assert.ok(route);
  assert.equal((await route.fetch(new Request('http://host/api/session.asr'))).status, 400);
  const request = 'http://host/api/session.asr?sessionId=synthetic';
  const response = await route.fetch(new Request(request));
  assert.equal(response.status, 200);
  assert.match(response.headers.get('content-type'), /application\/vnd.agent-session/);
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.equal((await route.fetch(new Request(request, { method: 'HEAD' }))).body, null);
  failure = Object.assign(new Error('private detail'), { code: 'SESSION_QUERY_SESSION_NOT_FOUND' });
  assert.equal((await route.fetch(new Request(request))).status, 404);
  failure = new Error('private detail');
  const failed = await route.fetch(new Request(request));
  assert.equal(failed.status, 500);
  assert.equal(await failed.text(), 'session export failed');
  await context.fiber.dispose();
  assert.equal(routes.size, 0);
});


test('native Host denies non-owner peers before the export route', async () => {
  const context = new Context();
  const provider = context.plugin(childContext => {
    new HostConnectionService(childContext, [], {});
    class Query extends Service {
      constructor() { super(childContext, 'sessionQuery'); }
      async readSession() { return snapshot; }
    }
    new Query();
  });
  await provider.await();
  const loaded = context.plugin(plugin);
  await loaded.await();
  try {
    const connection = context.get('connection');
    const shared = connection.createSharedFetchHandler('/api');
    const guest = connection.createPeer({ principal: { kind: 'test-guest', guest: 'synthetic' } });
    const request = () => new Request('http://host/api/session.asr?sessionId=synthetic');
    assert.equal((await shared.fetch(request(), guest)).status, 403);
    assert.equal((await shared.fetch(request(), connection.browserPeer)).status, 200);
    await loaded.dispose();
    assert.equal((await shared.fetch(request(), connection.browserPeer)).status, 404);
  } finally { await provider.dispose(); }
});
