"""Endpoint checks and private settings for opt-in synthetic agent runs."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def loopback_endpoint(value):
    """Require an explicit numeric loopback route before reading a credential."""
    try:
        parsed = urlsplit(value or "")
        valid = (parsed.scheme in ("http", "https") and parsed.hostname == "127.0.0.1"
                 and parsed.port is not None and parsed.port > 0 and not parsed.username and not parsed.password
                 and not parsed.query and not parsed.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("explicit_loopback_endpoint_required")
    return value.rstrip("/")


def private_json(path, value):
    path = Path(path)
    with path.open("x", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        json.dump(value, stream)
