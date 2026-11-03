import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';

for (const agent of ['gemini-cli', 'qwen-code']) {
  await build({
    entryPoints: [fileURLToPath(new URL('./cli.mjs', import.meta.url))],
    outfile: fileURLToPath(new URL(`../${agent}/dist/record.mjs`, import.meta.url)),
    bundle: true,
    platform: 'node',
    format: 'esm',
    target: 'node22',
    banner: { js: "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);" },
  });
}
