#!/usr/bin/env node
// Builds the site, exports it as static files with `mint export`, and deploys the result as a
// Cloudflare Worker with static assets (configured in wrangler.jsonc). See site/README.md.
//
// Usage: node deploy.mjs [--dry-run]
//   --dry-run  Export and prepare .export/, and run `wrangler deploy --dry-run`, without uploading.
//
// Wrangler must be logged in to the Cloudflare account that owns agentsessionrecord.org, or
// CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID must be set.

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { copyPublicAssets } from './public-assets.mjs';

const siteDir = path.dirname(fileURLToPath(import.meta.url));
const bin = (name) => path.join(siteDir, 'node_modules', '.bin', name);
const run = (cmd, args, cwd = siteDir) => execFileSync(cmd, args, { cwd, stdio: 'inherit' });

const { values } = parseArgs({ options: { 'dry-run': { type: 'boolean' } } });
const mintDir = path.join(siteDir, '.mint');
const zip = path.join(siteDir, '.export.zip');
const outDir = path.join(siteDir, '.export');

run(process.execPath, ['build.mjs', '--strict']);
run(bin('mint'), ['validate'], mintDir);
run(bin('mint'), ['broken-links'], mintDir);
run(bin('mint'), ['export', '--output', zip], mintDir);

fs.rmSync(outDir, { recursive: true, force: true });
fs.mkdirSync(outDir);
run('unzip', ['-q', zip, '-d', outDir]);
fs.rmSync(zip);
// Local-viewing helpers shipped in the export; not part of the hosted site.
for (const name of ['serve.js', 'README.md', 'Start Docs.bat', 'Start Docs.command']) {
  fs.rmSync(path.join(outDir, name), { force: true });
}
// Serve /spec/x from spec/x.html instead of redirecting to /spec/x/. The RSC payload stays at
// spec/x/index.txt, where worker.js looks for it.
for (const file of fs.readdirSync(outDir, { recursive: true })) {
  // `index/index.html` is the /index alias of the home page; moving it would replace the home page.
  if (path.basename(file) !== 'index.html' || ['.', 'index'].includes(path.dirname(file))) continue;
  if (path.dirname(file).split(path.sep)[0].startsWith('_')) continue;
  fs.renameSync(path.join(outDir, file), path.join(outDir, `${path.dirname(file)}.html`));
}
// Mintlify titles the home page "<title> - <name>", which repeats the name when they match.
const siteName = JSON.parse(fs.readFileSync(path.join(mintDir, 'docs.json'), 'utf8')).name;
for (const file of ['index.html', 'index.txt', 'index/index.html', 'index/index.txt']) {
  const target = path.join(outDir, file);
  if (!fs.existsSync(target)) continue;
  fs.writeFileSync(target, fs.readFileSync(target, 'utf8').replaceAll(`${siteName} - ${siteName}`, siteName));
}
// "Copy page" and "View as Markdown" fetch /<page>.md, which `mint export` does not produce.
for (const file of fs.readdirSync(mintDir, { recursive: true })) {
  if (!file.endsWith('.mdx')) continue;
  const mdx = fs.readFileSync(path.join(mintDir, file), 'utf8');
  const fm = mdx.match(/^---\n([\s\S]*?)\n---\n/);
  const field = (name) => fm?.[1].match(new RegExp(`^${name}:\\s*"?(.*?)"?\\s*$`, 'm'))?.[1];
  const body = fm ? mdx.slice(fm[0].length) : mdx;
  const header = [`# ${field('title') ?? ''}`, field('description')].filter(Boolean).join('\n\n');
  const dest = path.join(outDir, file.replace(/\.mdx$/, '.md'));
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.writeFileSync(dest, `${header}\n\n${body.replace(/^\n+/, '')}`);
}
// `mint export` drops JSON files, so restore the schemas and agent list explicitly.
copyPublicAssets(outDir);
for (const name of ['_headers', '404.html']) {
  fs.copyFileSync(path.join(siteDir, 'cloudflare', name), path.join(outDir, name));
}

run(bin('wrangler'), values['dry-run'] ? ['deploy', '--dry-run'] : ['deploy']);
