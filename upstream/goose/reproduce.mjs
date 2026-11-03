import { existsSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { reproducePackage } from '../../scripts/lib/upstream-package.mjs';

let checkout = process.argv[2];
if (checkout && !existsSync(path.join(checkout, '.git'))) {
  const children = readdirSync(checkout, { withFileTypes: true })
    .filter(entry => entry.isDirectory() && existsSync(path.join(checkout, entry.name, '.git')));
  if (children.length === 1) checkout = path.join(checkout, children[0].name);
}
await reproducePackage(new URL('./', import.meta.url), checkout);
