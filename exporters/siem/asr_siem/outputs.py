"""Offline request bodies. This module has no network client."""

from decimal import Decimal
import re

from .reader import json_text


def encode_output(events, target="ocsf", *, index="asr-audit"):
    if target == "ocsf":
        return "".join(json_text(event) + "\n" for event in events)
    if target == "splunk":
        return "".join(json_text({"time": Decimal(event["time"]) / 1000,
                                  "source": "asr", "sourcetype": "ocsf:asr", "event": event}) + "\n" for event in events)
    if target == "datadog":
        return json_text([{"ddsource": "asr", "service": "asr-siem", "message": "Recorded ASR audit event",
                           "timestamp": event["time"], "ocsf": event} for event in events]) + "\n"
    if target == "elastic":
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,200}", index) or index in (".", ".."):
            raise ValueError("invalid_index")
        return "".join(json_text({"index": {"_index": index, "_id": event["metadata"]["uid"]}}) + "\n" + json_text(event) + "\n" for event in events)
    raise ValueError("unknown_target")
