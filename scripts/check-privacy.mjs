#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { filesUnder, repositoryRoot } from './lib/files.mjs';

const patterns = [
  ['provider-token', /\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{20,})\b/],
  ['cloud-key', /\b(?:AKIA|ASIA)[A-Z0-9]{16}\b/],
  ['private-key', /-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----/],
  ['bearer-token', /\bBearer\s+[A-Za-z0-9._~+/-]{20,}/i],
  ['jwt', /\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}/],
  ['private-home-path', /(?:\/(?:home|Users)\/[^/\s"'<>\\]+|[A-Z]:[\\/]+Users[\\/]+[^\\/\s"'<>]+)/i],
  ['sensitive-phrase', /master[ _-]+password/i],
  ['account-id', /\b(?:acct|org)-[A-Za-z0-9]{12,}\b/],
];

const placeholder = /^(?:<[^>]+>|\$\{?[A-Z_][A-Z0-9_]*\}?|(?:example|test|synthetic|dummy|fake|placeholder|redacted)(?:[-_:].*)?|\[redacted\]|x{3,})$/i;
const assignment = /["']?((?:api|access|auth|refresh|secret)[_-]?(?:key|token)|session[_-]?token|password|(?:account|organization|tenant)[_-]?id)["']?\s*[:=]\s*["']([^"'\r\n]+)["']/gi;

export function privacyFindings(text) {
  const findings = [];
  for (const [index, line] of text.split('\n').entries()) {
    for (const [code, pattern] of patterns) {
      if (pattern.test(line)) findings.push({ line: index + 1, code });
    }
    for (const match of line.matchAll(assignment)) {
      if (!placeholder.test(match[2])) findings.push({ line: index + 1, code: 'sensitive-assignment' });
    }
  }
  return findings;
}

export function isFixtureFile(file) {
  return /(?:^|\/)(?:samples?|[^/]*fixtures?[^/]*|testdata)(?:\/|$)/i.test(file);
}

export function scanPrivacy(root) {
  const files = filesUnder(root, '', isFixtureFile).filter(isFixtureFile);
  const findings = files.flatMap((file) => privacyFindings(readFileSync(path.join(root, file), 'utf8'))
    .map((finding) => ({ file, ...finding })));
  return { files: files.length, findings };
}

function main() {
  const result = scanPrivacy(path.resolve(process.argv[2] ?? repositoryRoot));
  for (const { file, line, code } of result.findings) console.error(`${file}:${line}: ${code}`);
  console.log(`${result.files} sample and fixture files scanned, ${result.findings.length} findings. Values are never printed.`);
  process.exitCode = result.findings.length ? 1 : 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
