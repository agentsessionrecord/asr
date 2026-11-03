import { build } from 'esbuild';
import { execFileSync } from 'node:child_process';
import { copyFile } from 'node:fs/promises';
import { bundleViewer } from './bundle-viewer.mjs';
import { fileURLToPath } from 'node:url';
const dir = fileURLToPath(new URL('../', import.meta.url));
execFileSync(process.execPath, [fileURLToPath(new URL('../../viewer/build.mjs', import.meta.url))], { stdio: 'inherit', cwd: fileURLToPath(new URL('../../viewer/', import.meta.url)) });
await build({ entryPoints: [dir + 'src/extension.ts'], outfile: dir + 'dist/extension.js', bundle: true, platform: 'node', format: 'cjs', target: 'node22', external: ['vscode'] });
await build({ entryPoints: [dir + 'src/core.ts'], outfile: dir + 'dist/core.cjs', bundle: true, platform: 'node', format: 'cjs', target: 'node22' });
await bundleViewer(dir + 'dist/viewer.html');

await copyFile(new URL('../../../LICENSE', import.meta.url), new URL('../dist/LICENSE', import.meta.url));
