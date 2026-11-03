import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { repositoryRoot } from '../lib/files.mjs';

const read = file => readFileSync(path.join(repositoryRoot, file), 'utf8');

test('converter page covers every native discovery selector, path and override', () => {
  const page = read('site/pages/tools/convert.mdx').split('## Default native log locations')[1].split('## Converter library')[0];
  const selectors = [...read('crates/asr-convert/src/lib.rs').split('pub fn name(self)')[1]
    .split('pub fn ')[0].matchAll(/Self::\w+ => "([^"]+)"/g)].map(match => match[1]);
  const rows = [...page.matchAll(/^\| `([^`]+)` \|/gm)].map(match => match[1]);
  assert.ok(selectors.length > 40);
  assert.deepEqual(rows.sort(), selectors.sort());
  const discovery = read('crates/asr-collect/src/discovery.rs').split('#[cfg(test)]')[0];
  for (const [, value] of discovery.matchAll(/"([^"]+)"/g)) {
    assert.ok(page.includes(value), `document discovery value: ${value}`);
  }
});

test('security reporting gives a private contact and actionable reproduction guidance', () => {
  const reporting = read('SECURITY.md').split('## Report a vulnerability')[1]?.split('## Trust boundaries')[0];
  assert.ok(reporting);
  assert.match(reporting, /mailto:feedback@agentsessionrecord\.org/);
  assert.match(reporting, /handled privately/);
  assert.match(reporting, /affected tool and version/);
  assert.match(reporting, /impact/);
  assert.match(reporting, /steps to reproduce/);
});

test('Claude outcome notes cover explicit errors, structured results and unknown outcomes', () => {
  const notes = read('agents/claude-code.md');
  for (const value of ['is_error: true', 'is_error: false', 'toolUseResult', 'outcome stays unknown']) {
    assert.ok(notes.includes(value));
  }
  assert.match(notes, /When `is_error` is absent, a structured `toolUseResult` object also establishes completion/);
});

test('upstream proposals distinguish design feedback and state history setup once', () => {
  for (const name of ['README.md', 'PROPOSAL.md']) {
    assert.match(read(`upstream/codex/${name}`).split('\n')[0], /design feedback/);
  }
  assert.doesNotMatch(read('upstream/codex/README.md'), /## Install/);
  const proposal = read('upstream/opencode/PROPOSAL.md');
  assert.equal((proposal.match(/Restart an existing server with that setting/g) ?? []).length, 1);
  assert.doesNotMatch(proposal, /Enable durable event history before starting the server/);
});
