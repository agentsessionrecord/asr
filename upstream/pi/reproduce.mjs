import { reproducePackage } from '../../scripts/lib/upstream-package.mjs';
await reproducePackage(new URL('./', import.meta.url), process.argv[2]);
