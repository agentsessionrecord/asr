#!/usr/bin/env node
// Builds the white paper: whitepaper.md -> dist/whitepaper.html -> dist/agent-session-record-whitepaper.pdf.
//
//   node build.mjs                 HTML and PDF
//   node build.mjs --html-only     HTML only
//   node build.mjs --chrome=PATH   use a specific Chrome or Chromium binary (or set CHROME)
//
// Nothing is fetched at build time: the stylesheet is inlined and fonts come from the local system.
// The PDF is printed by headless Chrome. When poppler's pdftotext is installed, a second print
// fills the table of contents with page numbers read back from the first.

import { execFileSync, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import hljs from 'highlight.js/lib/core';
import bash from 'highlight.js/lib/languages/bash';
import json from 'highlight.js/lib/languages/json';
import plaintext from 'highlight.js/lib/languages/plaintext';
import MarkdownIt from 'markdown-it';
import { parse as parseYaml } from 'yaml';

import { prettyJsonText } from '../site/json-format.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const sourcePath = join(here, 'whitepaper.md');
const stylePath = join(here, 'style.css');
const distDir = join(here, 'dist');
const htmlPath = join(distDir, 'whitepaper.html');
const pdfPath = join(distDir, 'agent-session-record-whitepaper.pdf');

const args = process.argv.slice(2);
const htmlOnly = args.includes('--html-only');
const chromeOverride = args.find((a) => a.startsWith('--chrome='))?.slice('--chrome='.length) ?? process.env.CHROME;

hljs.registerLanguage('json', json);
hljs.registerLanguage('jsonl', json);
hljs.registerLanguage('bash', bash);
hljs.registerLanguage('shell', bash);
hljs.registerLanguage('text', plaintext);

const escapeHtml = (s) =>
  String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const cssString = (s) => `"${String(s).replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;

// ---------------------------------------------------------------------------
// Markdown

function splitFrontmatter(src) {
  const m = /^---\r?\n([\s\S]*?)\r?\n---\r?\n/.exec(src);
  if (!m) throw new Error('whitepaper.md must start with YAML frontmatter');
  const meta = parseYaml(m[1]) ?? {};
  for (const key of ['title', 'description']) {
    if (!meta[key]) throw new Error(`frontmatter is missing "${key}"`);
  }
  return { meta, body: src.slice(m[0].length) };
}

// Same rule as GitHub's heading anchors, so in-document links work in both places.
function uniqueSlug(text, seen) {
  const base = text
    .toLowerCase()
    .replace(/[^\p{L}\p{M}\p{N}\p{Pc} -]/gu, '')
    .replace(/ /g, '-');
  const count = seen.get(base) ?? 0;
  seen.set(base, count + 1);
  return count ? `${base}-${count}` : base;
}

function createRenderer() {
  const md = new MarkdownIt({
    html: true,
    typographer: true,
    highlight(code, lang) {
      const language = hljs.getLanguage(lang) ? lang : 'text';
      // JSON examples are pretty-printed the same way as on the site.
      const text = (/^jsonl?$/.test(lang) && prettyJsonText(code, 76)) || code.replace(/\n$/, '');
      const highlighted = hljs.highlight(text, { language, ignoreIllegals: true }).value;
      return `<pre class="code lang-${escapeHtml(lang || 'text')}"><code>${highlighted}</code></pre>`;
    },
  });

  // Heading anchors, section numbers and the outline used for the table of contents.
  md.core.ruler.push('outline', (state) => {
    const seen = new Map();
    const outline = (state.env.outline = []);
    const { tokens } = state;
    for (let i = 0; i < tokens.length; i++) {
      const open = tokens[i];
      if (open.type !== 'heading_open') continue;
      const inline = tokens[i + 1];
      const text = inline.children
        .filter((t) => t.type === 'text' || t.type === 'code_inline')
        .map((t) => t.content)
        .join('');
      const id = uniqueSlug(text, seen);
      open.attrSet('id', id);
      const entry = { level: Number(open.tag.slice(1)), id, number: null, title: text };
      const first = inline.children[0];
      const m = first?.type === 'text' ? /^(\d+(?:\.\d+)*)\.?\s+/.exec(first.content) : null;
      if (m) {
        entry.number = m[1];
        entry.title = text.slice(m[0].length);
        first.content = first.content.slice(m[0].length);
        const num = new state.Token('html_inline', '', 0);
        num.content = `<span class="secnum">${m[1]}</span>`;
        inline.children.unshift(num);
      }
      outline.push(entry);
    }
  });

  const defaultLinkOpen = md.renderer.rules.link_open ?? ((t, i, o, e, self) => self.renderToken(t, i, o));
  md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
    const href = tokens[idx].attrGet('href') ?? '';
    if (href.startsWith('#ref-')) tokens[idx].attrJoin('class', 'cite');
    else if (/^https?:/.test(href)) tokens[idx].attrJoin('class', 'ext');
    return defaultLinkOpen(tokens, idx, options, env, self);
  };

  md.renderer.rules.table_open = (tokens, idx) => {
    let columns = 0;
    for (let i = idx + 1; i < tokens.length && tokens[i].type !== 'tr_close'; i++) {
      if (tokens[i].type === 'th_open') columns++;
    }
    return `<div class="table-wrap"><table class="cols-${columns}${columns >= 6 ? ' wide' : ''}">\n`;
  };
  md.renderer.rules.table_close = () => '</table></div>\n';

  return md;
}

// Lets long URLs shown as link text break after slashes and before dots and dashes.
function breakableUrls(html) {
  return html.replace(/(<a [^>]*class="ext"[^>]*>)(https?:\/\/[^<]+)(<\/a>)/g, (_, open, url, close) =>
    open + url.replace(/\/(?!\/)/g, '/<wbr>').replace(/([.\-_])/g, '<wbr>$1') + close,
  );
}

// Wraps each level-2 section in <section class="sec sec-ID"> for styling and page breaks.
function wrapSections(html) {
  const parts = html.split(/(?=<h2 id=")/);
  return parts
    .map((part) => {
      const m = /^<h2 id="([^"]+)"/.exec(part);
      return m ? `<section class="sec sec-${m[1]}">\n${part}</section>\n` : part;
    })
    .join('');
}

// ---------------------------------------------------------------------------
// Page assembly

function renderCover(meta, abstractHtml) {
  const [main, rest] = String(meta.title).split(/:\s+(.*)/s);
  const title = rest
    ? `<span class="t-main">${escapeHtml(main)}:</span> <span class="t-rest">${escapeHtml(rest)}</span>`
    : escapeHtml(meta.title);
  const repo = meta.repository
    ? `<p class="cover-repo">${escapeHtml(meta.repository.replace(/^https?:\/\//, ''))}</p>`
    : '';
  return `<section class="cover">
  <div class="cover-band"></div>
  <h1 class="cover-title">${title}</h1>
  ${meta.subtitle ? `<p class="cover-subtitle">${escapeHtml(meta.subtitle)}</p>` : ''}
  <dl class="cover-meta">
    ${meta.version ? `<div><dt>Version</dt><dd>${escapeHtml(meta.version)}</dd></div>` : ''}
    ${meta.date ? `<div><dt>Date</dt><dd>${escapeHtml(meta.date)}</dd></div>` : ''}
    ${meta.authors ? `<div><dt>Authors</dt><dd>${escapeHtml(meta.authors)}</dd></div>` : ''}
  </dl>
  ${abstractHtml ? `<div class="cover-abstract">${abstractHtml}</div>` : ''}
  <div class="cover-foot">
    <p>Feedback: feedback@agentsessionrecord.org</p>
    ${repo}
  </div>
</section>
`;
}

function renderToc(outline, pages) {
  const items = outline
    .filter((e) => e.level === 2 || e.level === 3)
    .map((e) => {
      const page = pages?.get(e.id) ?? (pages ? '' : '88');
      return `<li class="toc-l${e.level}"><a href="#${e.id}"><span class="toc-num">${e.number ?? ''}</span><span class="toc-text">${escapeHtml(e.title)}</span><span class="toc-dots"></span><span class="toc-page">${page}</span></a></li>`;
    })
    .join('\n');
  return `<nav class="toc" aria-label="Contents">
<h2 class="toc-title">Contents</h2>
<ol>
${items}
</ol>
</nav>
`;
}

function pageRules(meta) {
  const left = String(meta.title).split(':')[0];
  const right = [meta.version, meta.date].filter(Boolean).join(' · ');
  return `@page {
  @top-left { content: ${cssString(left)}; }
  @top-right { content: ${cssString(right)}; }
  @bottom-center { content: counter(page); }
}`;
}

function renderDocument({ meta, bodyHtml, abstractHtml, outline, pages }) {
  const css = readFileSync(stylePath, 'utf8');
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(meta.title)}</title>
<meta name="description" content="${escapeHtml(meta.description)}">
<style>
${css}
${pageRules(meta)}
</style>
</head>
<body>
${renderCover(meta, abstractHtml)}
${renderToc(outline, pages)}
<main class="body">
${bodyHtml}
</main>
</body>
</html>
`;
}

// ---------------------------------------------------------------------------
// PDF

function findChrome() {
  if (chromeOverride) return chromeOverride;
  for (const name of ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser']) {
    if (spawnSync('which', [name], { stdio: 'ignore' }).status === 0) return name;
  }
  const mac = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  if (existsSync(mac)) return mac;
  throw new Error('Chrome not found; pass --chrome=PATH or set CHROME');
}

function printPdf(chrome) {
  const profile = mkdtempSync(join(tmpdir(), 'asr-whitepaper-chrome-'));
  try {
    execFileSync(
      chrome,
      [
        '--headless=new',
        '--no-pdf-header-footer',
        `--print-to-pdf=${pdfPath}`,
        `--user-data-dir=${profile}`,
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-background-networking',
        '--disable-component-update',
        '--disable-sync',
        '--disable-extensions',
        pathToFileURL(htmlPath).href,
      ],
      { stdio: ['ignore', 'ignore', 'pipe'] },
    );
  } finally {
    rmSync(profile, { recursive: true, force: true });
  }
}

const hasTool = (name, flag = '-v') => spawnSync(name, [flag], { stdio: 'ignore' }).status === 0;

// Reads the printed PDF back and finds the page each outline heading landed on.
function findHeadingPages(outline) {
  const text = execFileSync('pdftotext', ['-layout', '-enc', 'UTF-8', pdfPath, '-'], { encoding: 'utf8' });
  const squash = (s) => s.normalize('NFKC').replace(/\s+/g, '');
  const pages = text.split('\f').map((page) => page.split('\n').map(squash).filter(Boolean));
  const found = new Map();
  let from = 1; // skip the cover
  for (const entry of outline.filter((e) => e.level === 2 || e.level === 3)) {
    const key = squash(`${entry.number ?? ''}${entry.title}`);
    const prefix = key.slice(0, 28);
    // Table-of-contents lines end with a page number; heading lines never do.
    const isHeading = (line) =>
      !/\d$/.test(line) && (entry.number ? line.startsWith(prefix) || (line.length >= 12 && key.startsWith(line)) : line === key);
    for (let p = from; p < pages.length; p++) {
      if (pages[p].some(isHeading)) {
        found.set(entry.id, p + 1);
        from = p;
        break;
      }
    }
    if (!found.has(entry.id)) console.warn(`warning: no page found for heading "${entry.title}"`);
  }
  return found;
}

// ---------------------------------------------------------------------------

function main() {
  const { meta, body } = splitFrontmatter(readFileSync(sourcePath, 'utf8'));
  // The title block exists for GitHub and website readers; the PDF builds its own cover.
  const content = body.replace(/<!--\s*titleblock\s*-->[\s\S]*?<!--\s*\/titleblock\s*-->\s*/, '');

  const md = createRenderer();
  const env = {};
  let bodyHtml = wrapSections(breakableUrls(md.render(content, env)));
  const outline = env.outline.filter((e) => e.id !== 'abstract');

  // The abstract moves onto the cover.
  let abstractHtml = '';
  bodyHtml = bodyHtml.replace(/<section class="sec sec-abstract">\n([\s\S]*?)<\/section>\n/, (_, inner) => {
    abstractHtml = inner.replace(/<h2 id="abstract">/, '<h2 class="abstract-title">');
    return '';
  });

  mkdirSync(distDir, { recursive: true });
  const write = (pages) => writeFileSync(htmlPath, renderDocument({ meta, bodyHtml, abstractHtml, outline, pages }));
  write(null);
  console.log(`wrote ${relative(process.cwd(), htmlPath)}`);
  if (htmlOnly) return;

  const chrome = findChrome();
  printPdf(chrome);
  if (hasTool('pdftotext')) {
    write(findHeadingPages(outline));
    printPdf(chrome);
  } else {
    console.warn('warning: pdftotext not found; the table of contents has no page numbers');
    write(new Map());
    printPdf(chrome);
  }
  let pagesNote = '';
  if (hasTool('pdfinfo')) {
    const info = execFileSync('pdfinfo', [pdfPath], { encoding: 'utf8' });
    pagesNote = ` (${/^Pages:\s+(\d+)/m.exec(info)?.[1]} pages)`;
  }
  console.log(`wrote ${relative(process.cwd(), pdfPath)}${pagesNote}`);
}

main();
