import { record, parsePayload } from './recorder.mjs';
import { markAgentLoss } from '@agent-session/writer/capture';

// A recorder never returns a hook decision or changes the agent's exit status.
const lost = () => markAgentLoss(process.env.ASR_OUTPUT_DIR, process.argv[2]);
const deadline = setTimeout(() => { lost(); process.exit(0); }, 800).unref();
try {
  const chunks = [];
  let size = 0;
  for await (const chunk of process.stdin) {
    size += chunk.length;
    if (size > 1024 * 1024) { lost(); process.exit(0); }
    chunks.push(chunk);
  }
  record(process.argv[2], parsePayload(Buffer.concat(chunks).toString('utf8')), {
    directory: process.env.ASR_OUTPUT_DIR,
    full: process.env.ASR_CONTENT === 'full',
  });
} catch {
  lost();
} finally {
  clearTimeout(deadline);
}
