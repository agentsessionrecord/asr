#!/usr/bin/env node
// Empty stdout and exit zero express no decision in every supported command dialect.
let lost = () => {};
let deadline;
try {
  const [{ adapt }, { parse, record }] = await Promise.all([
    import('./adapters.mjs'), import('./recorder.mjs'),
  ]);
  const { markAgentLoss } = await import('../../packages/writer/dist/capture.js');
  lost = () => markAgentLoss(process.env.ASR_OUTPUT_DIR, process.argv[2]);
  deadline = setTimeout(() => { lost(); process.exit(0); }, 800).unref();
  let bytes = 0, chunks = [];
  for await (const chunk of process.stdin) {
    bytes += chunk.length;
    if (bytes > 1024 * 1024) { lost(); process.stdin.destroy(); break; }
    chunks.push(chunk);
  }
  if (bytes <= 1024 * 1024) {
    const event = adapt(process.argv[2], parse(Buffer.concat(chunks).toString('utf8')));
    if (event) record(process.argv[2], event);
    else lost();
  }
} catch { lost(); }
finally { clearTimeout(deadline); }
