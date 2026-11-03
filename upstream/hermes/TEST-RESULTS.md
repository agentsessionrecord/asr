# Verification

Date: 2026-11-03.

The project check script passes all 14 checks with its pinned Ruff. The focused export suite passes 10 tests.

| Project check | Result |
| --- | --- |
| `env HERMES_HOME={scratch}/hermes-home HERMES_RUNTIME_DIR={scratch}/hermes-runtime scripts/run_tests.sh tests/hermes_cli/test_session_export_asr.py tests/hermes_cli/test_session_export.py -q` | passed |
| `PATH={scratch}/uv-bin:$PATH python3 scripts/check` | passed |
| `PYTHONPATH=. HERMES_HOME={scratch}/hermes-home HERMES_RUNTIME_DIR={scratch}/hermes-runtime python3 {scratch}/native-python.py hermes` | passed |

The fresh synthetic native export validates with 9 records, 0 errors and 0 warnings. Package integrity and temporary-index patch replay results are recorded in `integration.json`. No current model run was made. Earlier live evidence is historical.
