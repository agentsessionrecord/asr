#!/usr/bin/env node
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { repositoryRoot } from './lib/files.mjs';

const repositoryUrl = 'https://github.com/agentsessionrecord/asr/blob/main/';
const jobs = ['index', 'convert', 'record', 'collect', 'view', 'export', 'import', 'patch'];

export function toolJob(entry) {
  if (entry.kind === 'converter' || entry.id === 'asr-convert') return 'convert';
  if (entry.kind === 'patch') return 'patch';
  if (entry.kind === 'importer' || entry.id === 'vendor-importer-core') return 'import';
  if (entry.kind === 'exporter') return 'export';
  if (entry.kind === 'app') return 'view';
  if (['asr-collect', 'asr-receive'].includes(entry.id)) return 'collect';
  if (['plugin', 'recorder', 'library'].includes(entry.kind)) return 'record';
  return 'index';
}

function nearbyReadme(root, entry) {
  let directory = path.join(root, entry.path);
  if (!existsSync(directory)) return undefined;
  if (!statSync(directory).isDirectory()) directory = path.dirname(directory);
  while (directory !== root) {
    const file = path.join(directory, 'README.md');
    if (existsSync(file)) return path.relative(root, file).split(path.sep).join('/');
    directory = path.dirname(directory);
  }
}

function markdownFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const file = path.join(directory, entry.name);
    return entry.isDirectory() ? markdownFiles(file) : /\.mdx?$/.test(file) ? [file] : [];
  });
}

export function checkToolDocs(root) {
  root = path.resolve(root);
  const problems = [];
  const entries = JSON.parse(readFileSync(path.join(root, 'registry.json'), 'utf8')).entries
    .filter(entry => entry.kind !== 'sample' && ['built', 'prototype', 'in-progress'].includes(entry.status));
  const navigation = JSON.parse(readFileSync(path.join(root, 'site/pages/docs.json'), 'utf8')).navigation;
  const routes = new Set();
  function visit(value) {
    if (typeof value === 'string') routes.add(value);
    else if (Array.isArray(value)) value.forEach(visit);
    else if (value && typeof value === 'object') Object.values(value).forEach(visit);
  }
  visit(navigation);
  const pages = new Map();
  for (const job of jobs) {
    const route = `tools/${job}`;
    const file = path.join(root, `site/pages/${route}.mdx`);
    if (!routes.has(route)) problems.push(`${route}: missing navigation entry`);
    if (!existsSync(file)) problems.push(`${route}: missing page`);
    else pages.set(job, readFileSync(file, 'utf8'));
  }
  const readmes = new Set();
  for (const entry of entries) {
    const readme = nearbyReadme(root, entry);
    if (!readme) {
      problems.push(`${entry.id}: missing nearby README`);
      continue;
    }
    readmes.add(readme);
    const link = `[${entry.name}](${repositoryUrl}${readme})`;
    const row = pages.get(toolJob(entry))?.split('\n').find(line => line.replaceAll('`', '').includes(link));
    if (!row) problems.push(`${entry.id}: missing README row on tools/${toolJob(entry)}`);
    else if (!row.includes(`\`${entry.liveTestStatus}\``)) problems.push(`${entry.id}: stale live-test status`);
  }
  const sources = [...readmes].map(file => path.join(root, file));
  const security = path.join(root, 'SECURITY.md');
  if (existsSync(security)) {
    sources.push(security);
    if (!pages.get('index')?.includes(`](${repositoryUrl}SECURITY.md)`)) {
      problems.push('tools/index: missing security guidance link');
    }
  }
  if (existsSync(path.join(root, 'site/pages/tools'))) sources.push(...markdownFiles(path.join(root, 'site/pages/tools')));
  for (const file of sources) {
    const text = readFileSync(file, 'utf8').replace(/^```[^\n]*\n[\s\S]*?^```\s*$/gm, '');
    for (const match of text.matchAll(/\]\(([^)\s]+)\)/g)) {
      const target = match[1].split('#')[0];
      if (!target) continue;
      let destination;
      if (target.startsWith(repositoryUrl)) destination = path.join(root, target.slice(repositoryUrl.length));
      else if (!/^(?:[a-z][a-z0-9+.-]*:|\/)/i.test(target)) destination = path.resolve(path.dirname(file), target);
      if (destination && !existsSync(destination)) problems.push(`${path.relative(root, file)}: missing link target ${target}`);
    }
  }
  return { entries: entries.length, readmes: readmes.size, pages: pages.size, problems };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const result = checkToolDocs(path.resolve(process.argv[2] ?? repositoryRoot));
  for (const problem of result.problems) console.error(problem);
  console.log(`${result.entries} tool entries, ${result.readmes} READMEs, ${result.pages} job pages, ${result.problems.length} errors.`);
  process.exitCode = result.problems.length ? 1 : 0;
}
