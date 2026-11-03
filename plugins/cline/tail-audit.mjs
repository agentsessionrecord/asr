#!/usr/bin/env node
import { openSync, closeSync, readSync, fstatSync } from 'node:fs';
import { setTimeout } from 'node:timers/promises';
import { StringDecoder } from 'node:string_decoder';
import { adapt } from '../remaining-core/adapters.mjs';
import { parse, record } from '../remaining-core/recorder.mjs';

// Follow only new complete lines. Historical import is a different producer method.
export async function follow(path, { signal, once = false, env = process.env } = {}) {
  const fd = openSync(path, 'r');
  let offset = fstatSync(fd).size, pending = '', skipPartial = false;
  const decoder = new StringDecoder('utf8');
  try {
    if (offset) {
      const last = Buffer.alloc(1);
      readSync(fd, last, 0, 1, offset - 1);
      skipPartial = last[0] !== 10;
    }
    do {
      const info = fstatSync(fd);
      if (info.size < offset) throw new Error('Audit log was truncated');
      const buffer = Buffer.alloc(Math.min(info.size - offset, 64 * 1024));
      const count = readSync(fd, buffer, 0, buffer.length, offset);
      offset += count;
      let next = buffer.subarray(0, count);
      if (skipPartial) {
        const boundary = next.indexOf(10);
        if (boundary < 0) next = next.subarray(next.length);
        else { skipPartial = false; next = next.subarray(boundary + 1); }
      }
      pending += decoder.write(next);
      if (Buffer.byteLength(pending) > 1024 * 1024) throw new Error('Audit line exceeds recorder limit');
      let end;
      while ((end = pending.indexOf('\n')) >= 0) {
        const line = pending.slice(0, end);
        pending = pending.slice(end + 1);
        const observation = adapt('cline', parse(line));
        record('cline', observation, { env });
      }
      if (!once && !signal?.aborted) {
        try { await setTimeout(100, undefined, { signal }); }
        catch (error) { if (!signal?.aborted) throw error; }
      }
    } while (!once && !signal?.aborted);
  } finally { closeSync(fd); }
}
if (process.argv[1]?.endsWith('/tail-audit.mjs')) {
  try { await follow(process.argv[2]); } catch { process.exitCode = 1; }
}
