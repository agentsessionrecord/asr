import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync, readdirSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';
import path from 'node:path';
import { tmpdir } from 'node:os';
import test from 'node:test';
import { repositoryRoot } from '../lib/files.mjs';

function additions(directory) {
  const manifest = JSON.parse(readFileSync(path.join(directory, 'manifest.json')));
  const files = new Map();
  for (const patch of manifest.patches) {
    const text = readFileSync(path.join(directory, patch.path), 'utf8');
    for (const diff of text.split(/^diff --git /m).slice(1)) {
      const name = /^a\/(.*?) b\//.exec(diff)?.[1];
      const added = diff.split('\n').filter(line => line.startsWith('+') && !line.startsWith('+++'))
        .map(line => line.slice(1)).join('\n');
      files.set(name, (files.get(name) ?? '') + '\n' + added);
    }
  }
  return files;
}

const rustHelpers = [];
const helperAgents = new Set();

for (const agent of readdirSync(path.join(repositoryRoot, 'upstream')).filter(name => name !== 'README.md')) {
  const directory = path.join(repositoryRoot, 'upstream', agent);
  const sources = additions(directory);
  test(`${agent}: source never asserts full reasoning`, () => {
    const proposal = readFileSync(path.join(directory, 'PROPOSAL.md'), 'utf8');
    for (const match of proposal.matchAll(/node upstream\/([a-z-]+)\/check\.mjs/g)) assert.equal(match[1], agent);
    assert.doesNotMatch(proposal, /Grok uses its append-only sidecar instead/);
    for (const [name, source] of sources) assert.doesNotMatch(source, /["']?visibility["']?\s*:\s*["']full["']/, name);
    for (const name of readdirSync(path.join(directory, 'samples/asr')).filter(name => name.endsWith('.jsonl'))) {
      for (const record of readFileSync(path.join(directory, 'samples/asr', name), 'utf8').trimEnd().split('\n').map(JSON.parse)) {
        for (const part of record.content ?? []) {
          if (part?.type !== 'reasoning') continue;
          assert.notEqual(part.visibility, 'full');
          if (part.visibility === 'summary') { assert.ok(part.summary?.length); assert.equal(part.text, undefined); }
          if (['omitted', 'encrypted'].includes(part.visibility)) { assert.equal(part.text, undefined); assert.equal(part.summary, undefined); }
        }
      }
    }
  });
  for (const [name, source] of sources) {
    if (name.endsWith('.ts') && source.includes('function asrReasoning(')) {
      helperAgents.add(agent);
      test(`${agent}: reasoning keeps exact unknown text, summaries and omitted content`, async () => {
        const helper = /function asrReasoning\([\s\S]*?\n\}/.exec(source)?.[0];
        assert.ok(helper);
        const js = stripTypeScriptTypes(helper + '\nexport { asrReasoning };');
        const module = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
        assert.deepEqual(module.asrReasoning(''), { type: 'reasoning', visibility: 'omitted' });
        assert.deepEqual(module.asrReasoning('', true), { type: 'reasoning', visibility: 'omitted' });
        assert.deepEqual(module.asrReasoning('Exact\r\n', true),
          { type: 'reasoning', visibility: 'summary', summary: ['Exact\r\n'] });
        assert.deepEqual(module.asrReasoning('Exact\r\n'), { type: 'reasoning', text: 'Exact\r\n' });
      });
    }
    if (name.endsWith('.py') && source.includes('def _asr_reasoning(')) {
      helperAgents.add(agent);
      test(`${agent}: Python reasoning preserves representation and empty markers`, () => {
        const helper = /def _asr_reasoning\([\s\S]*?(?=\n\S|$)/.exec(source)?.[0];
        assert.ok(helper);
        const program = helper + '\n' + [
          'assert _asr_reasoning("") == {"type":"reasoning", "visibility":"omitted"}',
          'assert _asr_reasoning("", True) == {"type":"reasoning", "visibility":"omitted"}',
          'assert _asr_reasoning("Exact\\r\\n", True) == {"type":"reasoning", "visibility":"summary", "summary":["Exact\\r\\n"]}',
          'assert _asr_reasoning("Exact\\r\\n") == {"type":"reasoning", "text":"Exact\\r\\n"}',
        ].join('\n');
        const result = spawnSync('python3', ['-I', '-c', program], { encoding: 'utf8' });
        assert.equal(result.status, 0, result.stderr);
      });
    }
    if (['gemini-cli', 'qwen-code'].includes(agent) && name.endsWith('/agent-session.ts')) {
      test(`${agent}: native content boundary omits signature-only thinking`, async () => {
        const code = stripTypeScriptTypes(source, { mode: 'transform' });
        const module = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
        const exporter = new module.SessionExport('synthetic.example');
        const parts = exporter.parts([
          { thought: true, text: 'Exact\r\n' },
          { thought: true, text: '' },
          { thoughtSignature: 'synthetic-opaque' },
          { thought: true, thoughtSignature: 'synthetic-opaque' },
        ]);
        assert.deepEqual(parts, [
          agent === 'gemini-cli' ? { type: 'reasoning', visibility: 'summary', summary: ['Exact\r\n'] }
            : { type: 'reasoning', text: 'Exact\r\n' },
          { type: 'reasoning', visibility: 'omitted' },
          { type: 'reasoning', visibility: 'omitted' },
          { type: 'reasoning', visibility: 'omitted' },
        ]);
      });
    }
    if (agent === 'deepagents' && name.endsWith('/deepagents_code/session_export.py')) {
      test('Deep Agents native content boundary preserves thinking representations', () => {
        const program = "scope = {'__name__': 'synthetic_asr'}\n" + `exec(${JSON.stringify(source)}, scope)\n` + [
          "parts, _ = scope['_parts']([{'type':'thinking','thinking':'Exact\\r\\n'}, {'type':'thinking','signature':'synthetic-opaque'}, {'type':'reasoning','reasoning':''}])",
          "assert parts == [{'type':'reasoning','visibility':'summary','summary':['Exact\\r\\n']}, {'type':'reasoning','visibility':'omitted'}, {'type':'reasoning','visibility':'omitted'}]",
        ].join('\n');
        const result = spawnSync('python3', ['-I', '-c', program], { encoding: 'utf8' });
        assert.equal(result.status, 0, result.stderr);
      });
    }
    if (name.endsWith('.go') && source.includes('func asrReasoning(')) {
      helperAgents.add(agent);
      test(`${agent}: Go reasoning preserves exact text and empty markers`, t => {
        const helper = /func asrReasoning\([\s\S]*?\n\}/.exec(source)?.[0];
        assert.ok(helper);
        const scratch = mkdtempSync(path.join(tmpdir(), 'asr-go-reasoning-'));
        t.after(() => rmSync(scratch, { recursive: true, force: true }));
        const program = 'package reasoning\nimport ("reflect"; "testing")\n' + helper + `
func TestRepresentation(t *testing.T) {
  for _, c := range []struct{text string; summary bool; want map[string]any}{
    {"", false, map[string]any{"type":"reasoning", "visibility":"omitted"}},
    {"", true, map[string]any{"type":"reasoning", "visibility":"omitted"}},
    {"Exact\\r\\n", true, map[string]any{"type":"reasoning", "visibility":"summary", "summary":[]string{"Exact\\r\\n"}}},
    {"Exact\\r\\n", false, map[string]any{"type":"reasoning", "text":"Exact\\r\\n"}},
  } { if got := asrReasoning(c.text, c.summary); !reflect.DeepEqual(got, c.want) { t.Fatalf("got %#v, want %#v", got, c.want) } }
}`;
        writeFileSync(path.join(scratch, 'reasoning_test.go'), program);
        const result = spawnSync('go', ['test', '-count=1', '.'], {
          cwd: scratch, encoding: 'utf8', env: { ...process.env, GO111MODULE: 'off' },
        });
        assert.equal(result.status, 0, result.stdout + result.stderr);
      });
    }
    if (name.endsWith('.rs') && source.includes('fn asr_reasoning(')) {
      helperAgents.add(agent);
      const helper = /fn asr_reasoning\([\s\S]*?\n\}/.exec(source)?.[0];
      assert.ok(helper);
      rustHelpers.push(`mod ${agent.replaceAll('-', '_')} { ${helper}
#[test] fn representation() {
  use serde_json::json;
  assert_eq!(asr_reasoning("", false), json!({"type":"reasoning", "visibility":"omitted"}));
  assert_eq!(asr_reasoning("", true), json!({"type":"reasoning", "visibility":"omitted"}));
  assert_eq!(asr_reasoning("Exact\\r\\n", true), json!({"type":"reasoning", "visibility":"summary", "summary":["Exact\\r\\n"]}));
  assert_eq!(asr_reasoning("Exact\\r\\n", false), json!({"type":"reasoning", "text":"Exact\\r\\n"}));
}
}`);
    }
  }
}

test('Rust producers preserve reasoning representations in their packaged helpers', t => {
  assert.equal(rustHelpers.length, 4);
  assert.deepEqual([...helperAgents].sort(), ['cline', 'continue', 'crush', 'deepagents', 'deepseek-harness', 'forgecode', 'gemini-cli', 'goose', 'hermes', 'kilo', 'kimi-code', 'mistral-vibe', 'mux', 'openclaw', 'opencode', 'pi', 'qwen-code', 'roo-code', 'shelley', 'warp', 'zed']);
  const scratch = mkdtempSync(path.join(tmpdir(), 'asr-rust-reasoning-'));
  t.after(() => rmSync(scratch, { recursive: true, force: true }));
  writeFileSync(path.join(scratch, 'Cargo.toml'), '[package]\nname="asr-reasoning-contracts"\nversion="0.0.0"\nedition="2024"\n[lib]\npath="lib.rs"\n[dependencies]\nserde_json="1"\n');
  writeFileSync(path.join(scratch, 'lib.rs'), rustHelpers.join('\n'));
  const result = spawnSync('cargo', ['test', '--offline', '--quiet'], {
    cwd: scratch, encoding: 'utf8',
    env: { ...process.env, CARGO_TARGET_DIR: path.join(repositoryRoot, 'target/reasoning-contracts') },
  });
  assert.equal(result.status, 0, result.stdout + result.stderr);
});

test('upstream fixes keep reviewable series and established CLI selection', () => {
  const directory = agent => path.join(repositoryRoot, 'upstream', agent);
  const claw = additions(directory('openclaw'));
  const manifest = JSON.parse(readFileSync(path.join(directory('openclaw'), 'manifest.json')));
  assert.equal(manifest.patches.length, 8);
  for (const name of claw.keys()) assert.doesNotMatch(name, /^(docs\/|config\/knip|scripts\/asr-export-fixture)/);
  for (const name of additions(directory('codex')).keys()) assert.doesNotMatch(name, /^codex-rs\/session-export\/scripts\//);
  const code = additions(directory('opencode'));
  assert.doesNotMatch(code.get('packages/cli/src/commands/commands.ts'), /aliases: \["sessions"\]|selected: Flag.String\("session"\)/);
  assert.doesNotMatch(code.get('packages/cli/src/commands/handlers/session/export.ts'), /input.selected/);
  for (const agent of ['codex', 'opencode', 'pi', 'openclaw']) {
    const proposal = readFileSync(path.join(directory(agent), 'PROPOSAL.md'), 'utf8');
    assert.doesNotMatch(proposal, /Grok uses its append-only sidecar instead/);
    assert.ok(proposal.includes(`node upstream/${agent}/check.mjs`));
  }
  const readme = readFileSync(path.join(directory('codex'), 'README.md'), 'utf8');
  assert.ok(readme.indexOf('[proposal]') < readme.indexOf('## Evaluate'));
  assert.match(readme, /does not accept external code contributions/);
  const proposal = readFileSync(path.join(directory('opencode'), 'PROPOSAL.md'), 'utf8');
  assert.ok(proposal.indexOf('OPENCODE_AGENT_SESSION_HISTORY=1') < proposal.indexOf('```'));
  assert.match(proposal, /anomalyco\/opencode/);
  assert.doesNotMatch(proposal, /opencode sessions|--session SESSION_ID/);
});
