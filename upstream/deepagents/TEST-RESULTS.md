# Verification

Date: 2026-11-03.

The package lint target includes Ruff and type checking. The package build and focused unit tests pass.

| Project check | Result |
| --- | --- |
| `uv sync --all-groups` | passed |
| `make test TEST_FILE="tests/unit_tests/test_session_export.py tests/unit_tests/test_main.py" PYTEST_EXTRA="-n 0" COV_ARGS=` | passed |
| `make lint PYTHON_FILES="deepagents_code/session_export.py deepagents_code/main.py deepagents_code/ui.py tests/unit_tests/test_session_export.py"` | passed |
| `uv build` | passed |
| `uv run --frozen python {scratch}/native-python.py deepagents` | passed |

The fresh synthetic native export validates with 6 records, 0 errors and 0 warnings. Package integrity and temporary-index patch replay results are recorded in `integration.json`. No current model run was made. Earlier live evidence is historical.
