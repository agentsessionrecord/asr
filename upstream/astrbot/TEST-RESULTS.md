# Verification

Date: 2026-11-03.

The project does not install Pyright as a dependency. The focused file passes Pyright 1.1.409 using this project's Python environment.

| Project check | Result |
| --- | --- |
| `uv sync --frozen` | passed |
| `uv run --frozen pytest tests/test_session_export.py -q` | passed |
| `uv run --frozen ruff check astrbot/cli/__main__.py astrbot/cli/commands/cmd_sessions.py tests/test_session_export.py` | passed |
| `uv run --frozen ruff format --check astrbot/cli/__main__.py astrbot/cli/commands/cmd_sessions.py tests/test_session_export.py` | passed |
| `uv build` | passed |
| `uv run --frozen {checkouts}/mistral-vibe/.venv/bin/pyright --pythonpath .venv/bin/python astrbot/cli/commands/cmd_sessions.py` | passed |
| `uv run --frozen python {scratch}/native-python.py astrbot` | passed |

The fresh synthetic native export validates with 6 records, 0 errors and 0 warnings. Package integrity and temporary-index patch replay results are recorded in `integration.json`. No current model run was made. Earlier live evidence is historical.
