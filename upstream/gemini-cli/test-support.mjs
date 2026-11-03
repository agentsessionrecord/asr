import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';
import ts from 'typescript';
import { validate } from '../../tools/validator/src/index.js';
import { validateWithSchema } from '../../tools/validator/src/schema/validate.js';

export async function loadPatch(directory) {
  const scratch = mkdtempSync(path.join(tmpdir(), 'asr-native-patch-'));
  const base = 'packages/cli/src/commands/sessions/';
  try {
    const applied = spawnSync('git', ['apply', `--include=${base}agent-session.ts`, `--include=${base}export.ts`, path.join(directory, 'patches/0001-native-agent-session-export.patch')], { cwd: scratch, encoding: 'utf8' });
    assert.equal(applied.status, 0, applied.stderr);
    writeFileSync(path.join(scratch, 'package.json'), '{"type":"module"}\n');
    for (const name of ['agent-session', 'export']) {
      const source = readFileSync(path.join(scratch, base, `${name}.ts`), 'utf8');
      const result = ts.transpileModule(source, { reportDiagnostics: true, compilerOptions: { target: ts.ScriptTarget.ES2023, module: ts.ModuleKind.ESNext, strict: true, verbatimModuleSyntax: true } });
      assert.equal(result.diagnostics?.length ?? 0, 0, 'TypeScript syntax diagnostics');
      writeFileSync(path.join(scratch, base, `${name}.js`), result.outputText);
    }
    const module = await import(pathToFileURL(path.join(scratch, base, 'export.js')).href);
    const helper = await import(pathToFileURL(path.join(scratch, base, 'agent-session.js')).href);
    return { ...module, ...helper, cleanup: () => rmSync(scratch, { recursive: true, force: true }) };
  } catch (error) {
    rmSync(scratch, { recursive: true, force: true });
    throw error;
  }
}

export function registerTests(agent, directory) {
  test(`${agent}: patched exporter reproduces and validates its synthetic sample`, async () => {
    const loaded = await loadPatch(directory);
    try {
      const native = readFileSync(path.join(directory, 'samples/native/native.jsonl'), 'utf8');
      const expected = readFileSync(path.join(directory, 'samples/asr/session.jsonl'), 'utf8');
      assert.deepEqual(validateWithSchema('discovery', JSON.parse(readFileSync(path.join(directory, 'discovery.json'), 'utf8'))), []);
      const stream = loaded.exportSession(native);
      assert.equal(stream, expected);
      const result = validate(stream);
      assert.equal(result.valid, true, JSON.stringify(result.diagnostics));
      assert.deepEqual(result.diagnostics, []);
      const rows = stream.trimEnd().split('\n').map(JSON.parse);
      assert.equal(rows[0].producer.method, 'native');
      assert.equal(rows.filter((r) => r.type === 'tool_call').length, 1);
      assert.equal(rows.filter((r) => r.type === 'tool_result').length, 1);
      assert.equal(rows.find((r) => r.type === 'tool_result').status, 'completed');
      assert.equal(rows.find((r) => r.id === 'prompt').content[0].text, 'Read the synthetic example.\n');
      assert.ok(rows.findIndex((r) => r.id === 'notice') < rows.findIndex((r) => r.type === 'tool_result'));
      assert.ok(!rows.some((r) => r.type === 'approval' || r.type === 'inference'));
      assert.equal(rows[0].endedAt, undefined);
    } finally { loaded.cleanup(); }
  });

  test(`${agent}: corruption, precision, secrets, identities and output selection`, async () => {
    const loaded = await loadPatch(directory);
    const scratch = mkdtempSync(path.join(tmpdir(), 'asr-native-selection-'));
    try {
      const native = readFileSync(path.join(directory, 'samples/native/native.jsonl'), 'utf8');
      const check = (source) => {
        const stream = loaded.exportSession(source);
        const result = validate(stream);
        assert.equal(result.valid, true, JSON.stringify(result.diagnostics));
        return stream.trimEnd().split('\n').map(JSON.parse);
      };
      const corrupt = check(native + 'invalid\n' + '{"incomplete":');
      assert.equal(corrupt.filter((r) => r.type === 'gap').length, 2);
      const hidden = check(native.replace('Read the synthetic example.', 'Bearer ' + 'z'.repeat(32)));
      assert.ok(hidden[0].missing.includes('secrets'));
      assert.equal(hidden.find((r) => r.id === 'prompt').truncated, true);
      assert.ok(!JSON.stringify(hidden).includes('z'.repeat(32)));
      assert.equal(loaded.parseNative('{"input":9007199254740993}').input, '9007199254740993');
      assert.throws(() => loaded.exportSession('{}\n'), /identity/);
      assert.throws(() => loaded.exportFiles({ format: 'agent-session' }, [], loaded.exportSession), /exactly one/);
      assert.throws(() => loaded.exportFiles({ format: 'agent-session', session: ['missing'] }, [], loaded.exportSession), /unavailable/);
      const source = path.join(scratch, 'input.jsonl');
      writeFileSync(source, native);
      const output = path.join(scratch, 'output');
      loaded.exportFiles({ format: 'agent-session', output }, [source], loaded.exportSession);
      assert.throws(() => loaded.exportFiles({ format: 'agent-session', output }, [source], loaded.exportSession), /EEXIST/);
      const patch = readFileSync(path.join(directory, 'patches/0001-native-agent-session-export.patch'), 'utf8');
      assert.match(patch, /\.command\(exportCommand\)/);
    } finally { loaded.cleanup(); rmSync(scratch, { recursive: true, force: true }); }
  });
}
