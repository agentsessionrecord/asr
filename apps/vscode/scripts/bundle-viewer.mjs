import { readFile, mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../../../', import.meta.url));
export async function bundleViewer(output) {
  const html = await readFile(path.join(root, 'apps/viewer/dist/index.html'), 'utf8');
  await mkdir(path.dirname(output), { recursive: true });
  await writeFile(output, html);
}
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  await bundleViewer(path.resolve(process.argv[2]));
}
