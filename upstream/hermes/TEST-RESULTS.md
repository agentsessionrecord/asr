# Verification

Date: 2026-11-05.

The project check script passes all 14 checks with its pinned Ruff. The focused export suite passes 11 tests.

| Project check | Result |
| --- | --- |
| `env HERMES_HOME={scratch}/hermes-home HERMES_RUNTIME_DIR={scratch}/hermes-runtime scripts/run_tests.sh tests/hermes_cli/test_session_export_asr.py tests/hermes_cli/test_session_export.py -q` | passed |
| `PATH={scratch}/uv-bin:$PATH python3 scripts/check` | passed |
| `PYTHONPATH=. HERMES_HOME={scratch}/hermes-home HERMES_RUNTIME_DIR={scratch}/hermes-runtime python3 {scratch}/sample-replay.py {package}/samples/native/native.json {package}/samples/asr/session.jsonl` | passed |

The packaged synthetic native sample exports byte for byte as the packaged ASR sample, which validates with 9 records, 0 errors and 0 warnings. Package integrity and temporary-index patch replay results are recorded in `integration.json`.

## Live run

On 2026-11-05 the patched CLI ran one isolated session with a Claude model through an OpenAI-compatible endpoint, using a scratch Hermes home and project. The agent read two files, edited one and ran its unit test. `hermes sessions export --format agent-session --session-id SESSION_ID` then exported the stored history.

| Live export | Result |
| --- | --- |
| Records | 13 |
| Messages | 3, one user and two assistant |
| Tool calls and results | 4 calls and 4 results, all paired by call ID |
| Validator | 0 errors, 0 warnings |

Each stored row maps to the records above, and nothing is added. An assistant turn that only requests tools is stored with empty text and exports as its tool calls alone. The edit appears as a `patch` tool call and its result. File changes, usage, model and exit codes are declared missing, as the proposal describes.
