import { checkPackage } from '../../scripts/lib/upstream-package.mjs';
await checkPackage(new URL('./', import.meta.url));
