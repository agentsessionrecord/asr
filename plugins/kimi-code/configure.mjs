import { configuration } from '../remaining-core/configure.mjs';
process.stdout.write(configuration('kimi-code', { kimiVersion: process.argv.includes('--v2') ? 2 : 1 }));
