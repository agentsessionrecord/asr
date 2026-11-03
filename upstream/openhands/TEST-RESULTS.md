# Verification

Date: 2026-11-03.

Focused tests pass 37 cases in five files. App and library builds pass. Full lint includes type checking. Actual Canvas end-to-end execution remains a contribution gate.

| Project check | Result |
| --- | --- |
| `npm ci --ignore-scripts` | passed |
| `npm run build` | passed |
| `npm run build:lib` | passed |
| `npm exec -- esbuild src/utils/transcript-export/agent-session.ts --bundle --platform=node --format=esm --alias:#=./src --outfile={scratch}/openhands-export.mjs` | passed |
| `npm test -- src/utils/transcript-export __tests__/components/features/conversation/transcript-export-modal.test.tsx src/api/no-direct-agent-server-calls.test.ts` | passed |
| `npm exec -- prettier --check __tests__/components/features/conversation/transcript-export-modal.test.tsx` | passed |
| `npm exec -- prettier --write src/components/features/conversation/transcript-export-modal.tsx __tests__/components/features/conversation/transcript-export-modal.test.tsx` | passed |
| `npm run lint` | passed |
| `Bundled native mapper fixture and exact sample comparison` | passed |
| `node {repository}/tools/validator/bin/asr-validate.js --json {package-root}/openhands/samples/asr/session.jsonl` | passed |

The fresh synthetic native export validates with 4 records, 0 errors and 0 warnings. Package integrity and temporary-index patch replay results are recorded in `integration.json`. No current model run was made. Earlier live evidence is historical.
