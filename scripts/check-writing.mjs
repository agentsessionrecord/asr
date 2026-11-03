#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { filesUnder, repositoryRoot } from './lib/files.mjs';

// Keep the public-writing checks from the documentation briefs together.
const history = /agent trace|earlier draft|previous draft|was removed|no longer|v3\.[0-9]|fitted|priority tool|admission rule|written exception|experimental tier|v321|fixture-verified|no-model|harness-authors|langfuse|complian(t|ce with)|non-normative|\bc[t]x\b|c[t]xrs/i;
const agentName = /t[3] code|t[3]code|t[3]-code|codes\.t[3]/i;
const internalName = /\bc[t]x(?:-[a-z][a-z-]*)?\b|c[t]xrs/i;
const localPath = /\$(?:WORK[T]REES|ASR_RE[S]EARCH)\b|(?<![A-Za-z0-9_.-])\/(?:home|Users)\/[^/\s"'<>\\]+|[A-Z]:[\\/]+Users[\\/]+[^\\/\s"'<>]+/i;
const disclosure = /^The author also builds \[c[t]x\]\(\), an open-source converter and search tool for agent sessions\.$/i;
const environment = /\b83[1]7\b|\bgpt-\d+(?:\.\d+)?-(?:s[o]l|l[u]na|a[s]tra|f[a]ble)\b|\bhai[k]u\b/i;
// Include wrapped prose and the added-line prefix in documentation patches.
const endpointWording = /\blocal(?:[\s-]+(?:\+\s*)?[a-z0-9-]+)*?[\s-]+(?:\+\s*)?pr[o]xy\b/gi;
const reportName = /(?:^|\/)reviews\/|(?:^|\/)[^/]*(?:REPORT|FEEDBACK)[^/]*\.md$/i;
const reportReference = /(?:^|[\s(/])reviews\/|\b(?:BUILD[-_]REPORT|SPEC[-_]FEEDBACK|IMPLEMENTATION[-_](?:REPORT|FEEDBACK))\.md\b/i;

export function checkWriting(text, file) {
  const findings = [];
  for (const match of text.matchAll(endpointWording)) {
    findings.push({ line: text.slice(0, match.index).split('\n').length, code: 'local-environment' });
  }
  if (reportName.test(file)) findings.push({ line: 1, code: 'internal-report-file' });
  const markdown = /\.(md|mdx)$/i.test(file);
  let fence;
  let frontmatter = false;
  let comment = false;
  for (const [index, line] of text.split('\n').entries()) {
    // Identity catalogs and their generated schemas contain registered names.
    const catalog = file === 'agents/agents.json' || (file === 'agents/index.md' && /^\s*\|/.test(line))
      || /^(?:schema\/v0|python\/agent_session_record\/src\/agent_session_record\/_schemas)\/(?:agent-session|manifest)\.schema\.json$/.test(file)
      || (file === 'tools/validator/src/schema/build.js' && line.startsWith('export const AGENT_NAMES = '));
    const disclosed = file === 'whitepaper/whitepaper.md' && disclosure.test(line.replace(/https?:\/\/[^\s)>]+/g, ''));
    // The pinned upstream framework names its Context parameter this way.
    // This is a native API identifier, rather than an internal tool reference.
    const names = /^upstream\/deepseek-harness\/patches\//.test(file)
      ? line.replace(/\bc[t]x(?=[:,).])/g, 'context') : line;
    const upstreamContext = /^upstream\/[^/]+\/patches\//.test(file) && /^(?: |@@)/.test(line);
    if (internalName.test(names) && !disclosed && !upstreamContext) findings.push({ line: index + 1, code: 'internal-name' });
    if (agentName.test(line) && !catalog) findings.push({ line: index + 1, code: 'agent-name' });
    if (localPath.test(line)) findings.push({ line: index + 1, code: 'local-path' });
    if (/build\s+governor/i.test(line)
      || ((markdown || /\.(?:[cm]?[jt]sx?|py|sh|bash|ps1)$/i.test(file)
        || /(?:^|[/.])(?:example|sample)(?:[/.]|$)/i.test(file)) && environment.test(line))) {
      findings.push({ line: index + 1, code: 'local-environment' });
    }
    if (/Task:\s*`|Branch:\s*`codex\//i.test(line) || reportReference.test(line)) {
      findings.push({ line: index + 1, code: 'internal-report-reference' });
    }
    if (!markdown) continue;
    if (index === 0 && line === '---') { frontmatter = true; continue; }
    if (frontmatter) {
      if (line === '---') frontmatter = false;
      continue;
    }
    const marker = /^ {0,3}(`{3,}|~{3,})/.exec(line);
    if (marker) {
      if (!fence) fence = marker[1];
      else if (marker[1][0] === fence[0] && marker[1].length >= fence.length) fence = undefined;
      continue;
    }
    if (fence) continue;
    let prose = line.replace(/<!--.*?-->/g, '');
    if (comment) {
      const end = prose.indexOf('-->');
      if (end < 0) continue;
      prose = prose.slice(end + 3);
      comment = false;
    }
    if (prose.includes('<!--')) {
      prose = prose.slice(0, prose.indexOf('<!--'));
      comment = true;
    }
    prose = prose.replace(/(`+).*?\1/g, '')
      .replace(/https?:\/\/[^\s)>]+/g, '')
      .replace(/<[^>]*>|&(?:#\d+|#x[\da-f]+|[a-z]+);/gi, '');
    if (/[;→—]/.test(prose)) findings.push({ line: index + 1, code: 'prose-punctuation' });
    if (history.test(prose) && !(file === 'whitepaper/whitepaper.md' && disclosure.test(prose))) {
      findings.push({ line: index + 1, code: 'writing-rule' });
    }
  }
  return findings;
}

export function scanWriting(root) {
  const files = filesUnder(root).filter((file) => file !== '.git' && !/(?:^|\/)(?:pnpm-lock\.yaml|uv\.lock|Cargo\.lock|go\.sum)$/.test(file)
    && !readFileSync(path.join(root, file)).includes(0));
  const findings = files.flatMap((file) => checkWriting(readFileSync(path.join(root, file), 'utf8'), file)
    .map((finding) => ({ file, ...finding })));
  return { files: files.length, findings };
}

function main() {
  const result = scanWriting(path.resolve(process.argv[2] ?? repositoryRoot));
  for (const { file, line, code } of result.findings) console.error(`${file}:${line}: ${code}`);
  console.log(`${result.files} public text files checked, ${result.findings.length} writing-rule findings.`);
  process.exitCode = result.findings.length ? 1 : 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
