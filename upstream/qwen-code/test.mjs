import { fileURLToPath } from 'node:url';
import { registerTests } from '../gemini-cli/test-support.mjs';
registerTests('qwen-code', fileURLToPath(new URL('.', import.meta.url)));
