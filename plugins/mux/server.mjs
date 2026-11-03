#!/usr/bin/env node
import { createInterface } from 'node:readline';
import { adapt } from '../remaining-core/adapters.mjs';
import { parse, record } from '../remaining-core/recorder.mjs';

const lines = createInterface({ input: process.stdin });
for await (const line of lines) {
  let request;
  try {
    if (Buffer.byteLength(line) > 1024 * 1024) continue;
    request = parse(line);
    if (!Object.hasOwn(request, 'id')) continue;
    let result;
    if (request.method === 'initialize') result = { protocolVersion: '2024-11-05',
      serverInfo: { name: 'asr-mux-recorder', version: '0.1.0' }, capabilities: { tools: {} } };
    else if (request.method === 'ping') result = {};
    else if (request.method === 'tools/list') result = { tools: [{ name: 'observe',
      description: 'Passively record one local hook observation.', inputSchema: { type: 'object', additionalProperties: true } }] };
    else if (request.method === 'tools/call' && request.params?.name === 'observe') {
      try { record('mux', adapt('mux', request.params.arguments)); } catch {}
      // An empty JSON object is a valid no-op hook response, including on failure.
      result = { content: [{ type: 'text', text: '{}' }] };
    } else {
      process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: request.id, error: { code: -32601, message: 'Method not found' } }) + '\n');
      continue;
    }
    process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: request.id, result }) + '\n');
  } catch {
    if (request?.id !== undefined) process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: request.id,
      result: { content: [{ type: 'text', text: '{}' }] } }) + '\n');
  }
}
