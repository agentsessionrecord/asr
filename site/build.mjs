#!/usr/bin/env node
// Assembles the Mintlify site in site/.mint/ from the hand-written pages in site/pages/ and the
// repository's Markdown sources, then checks every internal link and anchor. See site/README.md.
//
// Usage: node build.mjs [--strict]
//   --strict  Fail when the white paper PDF has not been built (use before deploying).

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import GithubSlugger from 'github-slugger';

import { prettyJsonText } from './json-format.mjs';
import { copyPublicAssets } from './public-assets.mjs';

const siteDir = path.dirname(fileURLToPath(import.meta.url));
const repoDir = path.resolve(siteDir, '..');
const outDir = path.join(siteDir, '.mint');
const strict = process.argv.includes('--strict');

const PDF_NAME = 'agent-session-record-whitepaper.pdf';
const SECTIONS = ['spec', 'guides', 'agents'];
const FRONTMATTER = /^---\n([\s\S]*?)\n---\n/;

const errors = [];
const warnings = [];

/** Rewrites a repository-relative Markdown link (`format.md#x`, `../guides/otel.md`) to a site route. */
function rewriteLink(target, section) {
  if (/^[a-z][a-z0-9+.-]*:/i.test(target) || target.startsWith('#') || target.startsWith('/')) return target;
  const [file, hash] = target.split('#');
  if (!/\.mdx?$/.test(file)) {
    errors.push(`${section}: cannot map relative link "${target}" to a site page`);
    return target;
  }
  const route = path.posix.normalize(`${section}/${file}`)
    .replace(/^site\/pages\//, '').replace(/\.mdx?$/, '').replace(/(?:^|\/)index$/, '');
  return `/${route}${hash ? `#${hash}` : ''}`;
}


/**
 * JSON and JSON Lines examples are shown expanded for reading: each record is pretty-printed,
 * with short objects kept on one line, and records are separated by a blank line. The sources
 * keep one record per line, as a stream does, and are what the validator checks. Blocks that
 * do not parse are left as written.
 */
function formatCodeBlock(block) {
  const m = block.match(/^```(jsonl?)([^\n]*)\n([\s\S]*?)^```$/m);
  if (!m) return block;
  const [lang, title] = [m[1], m[2]];
  const info = /\bwrap\b/.test(title) ? title : `${title} wrap`;
  const body = prettyJsonText(m[3]);
  return body ? `\`\`\`${lang}${info}\n${body}\n\`\`\`` : `\`\`\`${lang}${info}\n${m[3]}\`\`\``;
}

/**
 * Converts CommonMark written for GitHub into MDX: rewrites links, turns autolinks and HTML
 * comments into MDX equivalents and escapes braces. Inline code is left untouched; JSON code
 * blocks are expanded for reading by formatCodeBlock.
 */
function toMdx(body, section) {
  return body
    .split(/(^```[\s\S]*?^```)/m)
    .map((chunk, i) => {
      if (i % 2 === 1) return formatCodeBlock(chunk);
      const code = [];
      let t = chunk.replace(/`[^`\n]*`/g, (c) => `\u0000${code.push(c) - 1}\u0000`);
      t = t.replace(/<!--([\s\S]*?)-->/g, '');
      t = t.replace(/[{}]/g, (c) => `\\${c}`);
      t = t.replace(/\]\(([^)\s]+)\)/g, (_, target) => `](${rewriteLink(target, section)})`);
      t = t.replace(/<(https?:\/\/[^>\s]+)>/g, '[$1]($1)');
      t = t.replace(/<br>/g, '<br />');
      return t.replace(/\u0000(\d+)\u0000/g, (_, n) => code[Number(n)]);
    })
    .join('');
}

function splitFrontmatter(text, file) {
  const m = text.match(FRONTMATTER);
  if (!m) throw new Error(`${file} must start with YAML frontmatter`);
  return { frontmatter: m[1], body: text.slice(m[0].length) };
}

function write(rel, content) {
  const dest = path.join(outDir, rel);
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.writeFileSync(dest, content);
}

function convertSection(section) {
  const dir = path.join(repoDir, section);
  for (const name of listPages(dir).sort()) {
    if (!name.endsWith('.md') || /^readme\.md$/i.test(name)) continue;
    const { frontmatter, body } = splitFrontmatter(fs.readFileSync(path.join(dir, name), 'utf8'), `${section}/${name}`);
    // Starlight's sidebar ordering is replaced by the navigation in docs.json.
    const fm = frontmatter.replace(/^sidebar:\n(?:[ \t]+.*(?:\n|$))*/m, '').trimEnd();
    write(`${section}/${name.replace(/\.md$/, '.mdx')}`, `---\n${fm}\n---\n\n${toMdx(body, path.posix.dirname(`${section}/${name}`)).replace(/^\n+/, '')}`);
  }
}

function convertWhitepaper() {
  const src = path.join(repoDir, 'whitepaper', 'whitepaper.md');
  const { body } = splitFrontmatter(fs.readFileSync(src, 'utf8'), 'whitepaper/whitepaper.md');
  const content = body.replace(/<!--\s*titleblock\s*-->[\s\S]*?<!--\s*\/titleblock\s*-->\s*/, '');
  const header = [
    '---',
    'title: "White paper"',
    'description: "Agent Session Record: an open format for recorded agent sessions. A white paper by Wills Manley."',
    '---',
    '',
    `<Card title="Download the PDF" icon="file-pdf" href="/downloads/${PDF_NAME}" horizontal />`,
    '',
    '',
  ].join('\n');
  write('whitepaper.mdx', header + toMdx(content, 'whitepaper'));

  const pdf = path.join(repoDir, 'whitepaper', 'dist', PDF_NAME);
  if (fs.existsSync(pdf)) {
    fs.mkdirSync(path.join(outDir, 'downloads'), { recursive: true });
    fs.copyFileSync(pdf, path.join(outDir, 'downloads', PDF_NAME));
  } else {
    (strict ? errors : warnings).push(`whitepaper/dist/${PDF_NAME} is missing; build it with "node whitepaper/build.mjs"`);
  }
}

/**
 * Heading anchors on a page, ignoring fenced code. Returns a map from the anchor GitHub would
 * generate (which the Markdown sources link to) to the anchor Mintlify generates. They differ
 * only in that Mintlify turns dots into hyphens: "7.1 Identity" is #7-1-identity, not #71-identity.
 */
function anchorsOf(mdx) {
  const github = new GithubSlugger();
  const mintlify = new GithubSlugger();
  const anchors = new Map();
  for (const chunk of mdx.split(/^```[\s\S]*?^```/m)) {
    for (const m of chunk.matchAll(/^#{1,6}\s+(.+?)\s*#*\s*$/gm)) {
      const text = m[1].replace(/`/g, '').replace(/\\([{}])/g, '$1');
      anchors.set(github.slug(text), mintlify.slug(text.replace(/\./g, '-')));
    }
    for (const m of chunk.matchAll(/<a id="([^"]+)"/g)) anchors.set(m[1], m[1]);
  }
  return anchors;
}

function listPages(dir, prefix = '') {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const rel = prefix ? `${prefix}/${e.name}` : e.name;
    if (e.isDirectory()) return listPages(path.join(dir, e.name), rel);
    return /\.mdx?$/.test(e.name) ? [rel] : [];
  });
}

function checkLinks() {
  const pages = new Map();
  const files = new Map();
  for (const rel of listPages(outDir)) {
    const route = `/${rel.replace(/\.mdx?$/, '')}`.replace(/\/index$/, '') || '/';
    files.set(route, path.join(outDir, rel));
    pages.set(route, fs.readFileSync(path.join(outDir, rel), 'utf8'));
  }
  const anchors = new Map([...pages].map(([route, mdx]) => [route, anchorsOf(mdx)]));
  // Rewrite GitHub-style anchors in links to the anchors Mintlify generates.
  for (const [route, mdx] of pages) {
    const fixed = mdx.replace(/\]\((\/[^)#\s]*)?#([^)\s]+)\)/g, (all, p, hash) => {
      const map = anchors.get(p === undefined ? route : p.replace(/\/$/, '') || '/');
      const target = map?.get(hash);
      return target && target !== hash ? `](${p ?? ''}#${target})` : all;
    });
    if (fixed !== mdx) {
      pages.set(route, fixed);
      fs.writeFileSync(files.get(route), fixed);
    }
  }
  const navigation = JSON.stringify(JSON.parse(fs.readFileSync(path.join(outDir, 'docs.json'), 'utf8')).navigation);
  for (const page of navigation.match(/"[a-z0-9/-]+"/g).map((s) => s.slice(1, -1))) {
    if (page.includes('/') || page === 'index' || page === 'whitepaper') {
      const route = page === 'index' ? '/' : `/${page}`.replace(/\/index$/, '');
      if (!pages.has(route)) errors.push(`docs.json lists "${page}", which does not exist`);
    }
  }
  for (const [route, mdx] of pages) {
    const text = mdx.split(/^```[\s\S]*?^```/m).join('').replace(/`[^`\n]*`/g, '');
    const targets = [
      ...[...text.matchAll(/\]\(([^)\s]+)\)/g)].map((m) => m[1]),
      ...[...text.matchAll(/href="([^"]+)"/g)].map((m) => m[1]),
    ];
    for (const target of targets) {
      if (!(target.startsWith('/') || target.startsWith('#'))) continue;
      if (target.startsWith('/downloads/')) {
        if (!fs.existsSync(path.join(outDir, target)) && strict) errors.push(`${route}: missing download ${target}`);
        continue;
      }
      const [p, hash] = target.split('#');
      const dest = p === '' ? route : p.replace(/\/$/, '') || '/';
      const asset = path.join(outDir, p);
      if (p && fs.existsSync(asset) && fs.statSync(asset).isFile() && !/\.mdx?$/.test(p)) continue;
      if (!pages.has(dest)) {
        errors.push(`${route}: link to missing page ${target}`);
      } else if (hash && ![...anchors.get(dest).values()].includes(hash)) {
        errors.push(`${route}: link to missing anchor ${target}`);
      }
    }
  }
}

fs.rmSync(outDir, { recursive: true, force: true });
fs.cpSync(path.join(siteDir, 'pages'), outDir, { recursive: true });
for (const section of SECTIONS) convertSection(section);
convertWhitepaper();
copyPublicAssets(outDir);
// Hand-written pages get the same code block formatting as converted ones.
for (const rel of listPages(outDir)) {
  const file = path.join(outDir, rel);
  const mdx = fs.readFileSync(file, 'utf8');
  const formatted = mdx.replace(/^```[\s\S]*?^```/gm, formatCodeBlock);
  if (formatted !== mdx) fs.writeFileSync(file, formatted);
}
checkLinks();

for (const w of warnings) console.warn(`warning: ${w}`);
if (errors.length) {
  for (const e of errors) console.error(`error: ${e}`);
  process.exit(1);
}
console.log(`assembled ${path.relative(process.cwd(), outDir) || '.'}`);
