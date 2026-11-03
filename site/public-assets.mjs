import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

// Keep the assembled site and static export on the same explicit asset list.
const assets = [
  'schema/v0/agent-session.schema.json',
  'schema/v0/annotation.schema.json',
  'schema/v0/discovery.schema.json',
  'schema/v0/manifest.schema.json',
  'examples/collection.manifest.json',
  'agents/agents.json',
];

export function copyPublicAssets(outDir) {
  for (const relative of assets) {
    const source = path.join(repoDir, relative);
    const destination = path.join(outDir, relative);
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    fs.copyFileSync(source, destination);
  }
}
