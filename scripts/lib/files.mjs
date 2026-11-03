import { readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const repositoryRoot = fileURLToPath(new URL('../../', import.meta.url));

const generated = new Set([
  '.git', 'node_modules', 'target', '.venv', '__pycache__', '.pytest_cache',
  '.mint', '.export', '.wrangler', 'dist', 'vendor',
]);

export function filesUnder(directory, prefix = '', includeGenerated = () => false) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory() && (!generated.has(entry.name) || includeGenerated(relative))) {
      return filesUnder(path.join(directory, entry.name), relative, includeGenerated);
    }
    return entry.isFile() ? [relative] : [];
  }).sort();
}
