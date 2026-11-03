"""Exact JSON numbers at the ASR and artifact boundaries."""

import json
import math
from decimal import Decimal


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def loads(text):
    def invalid(_):
        raise ValueError("nonfinite_number")

    return json.loads(text, parse_float=Decimal, object_pairs_hook=_object, parse_constant=invalid)


def dumps(value):
    if value is None or isinstance(value, (bool, str, int)):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("nonfinite_number")
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("nonfinite_number")
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ",".join(map(dumps, value)) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k) + ":" + dumps(v) for k, v in value.items()) + "}"
    raise TypeError(type(value).__name__)
