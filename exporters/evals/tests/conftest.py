from pathlib import Path
from types import SimpleNamespace

import pytest

from asr_evals.reader import read_session

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def session():
    return read_session(FIXTURES / "session.jsonl")


@pytest.fixture
def options():
    return SimpleNamespace(include_content=False, inference_ts="end", tool_times=True, dataset_name="synthetic-asr-evals")
