"""Optional contract checks against pinned upstream SDKs, without API calls."""

import importlib.metadata
import json

import pytest

from asr_evals.dataset import rows


def test_langfuse_3_8_1_request_models(session, options):
    pytest.importorskip("langfuse")
    if importlib.metadata.version("langfuse") != "3.8.1":
        pytest.skip("contract check pins langfuse 3.8.1")
    from langfuse.api.resources.ingestion.types.ingestion_event import (
        IngestionEvent_TraceCreate, IngestionEvent_GenerationCreate,
        IngestionEvent_SpanCreate, IngestionEvent_EventCreate,
    )
    from langfuse.api.resources.dataset_items.types.create_dataset_item_request import CreateDatasetItemRequest
    from asr_langfuse import export

    options.include_content = True
    artifacts = export([session], rows([session], include_content=True), options)
    models = {"trace-create": IngestionEvent_TraceCreate, "generation-create": IngestionEvent_GenerationCreate,
              "span-create": IngestionEvent_SpanCreate, "event-create": IngestionEvent_EventCreate}
    for event in json.loads(artifacts["ingestion.json"])["batch"]:
        parsed = models[event["type"]].parse_obj(event)
        assert parsed.body.id == event["body"]["id"]
    for line in artifacts["dataset-items.jsonl"].splitlines():
        item = json.loads(line)
        assert CreateDatasetItemRequest.parse_obj(item).dataset_name == options.dataset_name


def test_braintrust_0_3_9_log_argument_validation(session, options):
    pytest.importorskip("braintrust")
    if importlib.metadata.version("braintrust") != "0.3.9":
        pytest.skip("contract check pins braintrust 0.3.9")
    from braintrust.logger import _validate_and_sanitize_experiment_log_partial_args
    from braintrust.span_types import SpanTypeAttribute
    from asr_braintrust import export

    artifacts = export([session], rows([session]), options)
    events = json.loads(artifacts["project-logs.json"])["events"]
    assert len(events) > 3
    for event in events:
        assert event["span_attributes"]["type"] in {t.value for t in SpanTypeAttribute}
        args = {key: value for key, value in event.items() if key not in {"id", "span_parents"}}
        assert _validate_and_sanitize_experiment_log_partial_args(args) == args
