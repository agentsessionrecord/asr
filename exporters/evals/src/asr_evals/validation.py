"""Read packaged schemas without a network resolver."""

import json
from importlib.resources import files

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


def _validators():
    documents = [json.loads(path.read_text(encoding="utf-8"))
                 for path in files("agent_session_record").joinpath("_schemas").iterdir()
                 if path.name.endswith(".json")]
    registry = Registry().with_resources((doc["$id"], Resource.from_contents(doc)) for doc in documents)
    return {doc["$id"].rsplit("/", 1)[-1]: Draft202012Validator(doc, registry=registry, format_checker=FormatChecker())
            for doc in documents}


VALIDATORS = _validators()


def valid_record(record, annotation=False):
    name = "annotation.schema.json" if annotation else "agent-session.schema.json"
    return VALIDATORS[name].is_valid(record)
