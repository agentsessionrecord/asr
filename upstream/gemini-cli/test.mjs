import { fileURLToPath } from 'node:url';
import { registerTests } from './test-support.mjs';
registerTests('gemini-cli', fileURLToPath(new URL('.', import.meta.url)));
