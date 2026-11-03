#!/usr/bin/env node
import Ajv2020 from 'ajv/dist/2020.js';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { repositoryRoot } from './lib/files.mjs';

export function checkRegistry(registry, schema, root) {
  const validate = new Ajv2020({ allErrors: true, strict: true }).compile(schema);
  if (!validate(registry)) {
    return validate.errors.map((error) => `${error.instancePath || '/'}: ${error.message}`);
  }
  const problems = [];
  const ids = new Set();
  for (const entry of registry.entries) {
    if (ids.has(entry.id)) problems.push(`Duplicate registry ID: ${entry.id}`);
    ids.add(entry.id);
    if (entry.liveTestStatus === 'passed') {
      const notes = entry.liveTestNotes ?? '';
      if (/^Prior revision\b/i.test(notes)
        || /(?:not live-tested|not live tested|was then refined|were then retained|not rebuilt|not rerun)/i.test(notes)
        || /^(?:(?:Local )?synthetic (?:Git )?repositories|Synthetic local Git|Local example|Pydantic v2 models and local writer|Local authenticated HTTP receiver tests)/i.test(notes)
        || /\b(?:unit tests? only|only (?:synthetic|local|unit) tests?|no agent inference is needed)\b/i.test(notes)) {
        problems.push(`${entry.id}: passed requires a live run of the current implementation`);
      }
    }
    if (entry.status !== 'elsewhere' && entry.location !== entry.path) {
      problems.push(`${entry.id}: local location must equal path`);
    }
    if (['built', 'prototype', 'in-progress'].includes(entry.status) && !existsSync(path.join(root, entry.path))) {
      problems.push(`${entry.id}: repository path does not exist`);
    }
  }
  return problems;
}

function main() {
  const root = path.resolve(process.argv[2] ?? repositoryRoot);
  const registry = JSON.parse(readFileSync(path.join(root, 'registry.json'), 'utf8'));
  const schema = JSON.parse(readFileSync(path.join(root, 'schema/registry.schema.json'), 'utf8'));
  const problems = checkRegistry(registry, schema, root);
  for (const problem of problems) console.error(problem);
  console.log(`${registry.entries?.length ?? 0} registry entries, ${problems.length} errors.`);
  process.exitCode = problems.length ? 1 : 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
