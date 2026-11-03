import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { checkPluginPackage } from './check.mjs';
const checkout = process.argv[2];
assert.ok(checkout, 'usage: node reproduce.mjs UPSTREAM_CHECKOUT');
const manifest = checkPluginPackage();
const result = spawnSync('git', ['cat-file', '-e', `${manifest.base}^{commit}`], { cwd: checkout, encoding: 'utf8' });
assert.equal(result.status, 0, result.stderr);
console.log('deepseek-harness: pinned API source exists, plugin fixture reproduced, checkout preserved');
