import { build } from 'esbuild';
import { mkdir, readFile, writeFile } from 'node:fs/promises';

const root = new URL('./', import.meta.url);
process.chdir(root.pathname);
const bundle = async (entry, platform = 'browser') => (await build({
  entryPoints: [entry], bundle: true, write: false, format: platform === 'node' ? 'esm' : 'iife',
  platform, target: 'es2022', legalComments: 'none',
})).outputFiles[0].text;
const worker = await bundle('src/worker.ts');
const app = await bundle('src/app.ts');
const template = await readFile(new URL('src/index.html', root), 'utf8');
const css = await readFile(new URL('src/style.css', root), 'utf8');
// Escape closing tags even if a future source string contains one.
const script = `const ASR_WORKER_SOURCE = ${JSON.stringify(worker)};\n${app}`.replace(/<\/script/gi, '<\\/script');
await mkdir(new URL('dist/', root), { recursive: true });
await writeFile(new URL('dist/index.html', root), template.replace('/* ASR_STYLE */', css).replace('/* ASR_SCRIPT */', script));
await writeFile(new URL('dist/core.mjs', root), await bundle('src/core.ts', 'node'));
console.log('Built apps/viewer/dist/index.html (self-contained, offline)');
