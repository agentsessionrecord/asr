"""OTLP/HTTP JSON delivery restricted to a configured loopback collector."""

import ipaddress
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .reader import exact_json


class DeliveryError(ValueError):
    pass


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def local_endpoint(endpoint):
    try:
        parsed = urlsplit(endpoint)
        address = ipaddress.ip_address(parsed.hostname or "")
        if (parsed.scheme not in {"http", "https"} or not address.is_loopback
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or parsed.port == 0
                or "%" in (parsed.hostname or "") or "\\" in endpoint
                or any(ord(c) < 33 for c in endpoint)):
            raise ValueError()
    except ValueError:
        raise DeliveryError("endpoint_must_be_numeric_loopback") from None
    return endpoint.rstrip("/")


def send(export, endpoint, timeout=10):
    base = local_endpoint(endpoint)
    opener = build_opener(ProxyHandler({}), NoRedirects())
    delivered = []
    for signal, document, field, rejected in (
            ("traces", export.traces, "resourceSpans", "rejectedSpans"),
            ("logs", export.logs, "resourceLogs", "rejectedLogRecords")):
        if not document[field]:
            continue
        request = Request(base + "/v1/" + signal,
                          data=exact_json(document).encode("utf-8"),
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with opener.open(request, timeout=timeout) as response:
                if not 200 <= response.status < 300:
                    raise DeliveryError(signal + "_http_failure")
                data = response.read(1_048_577)
            if len(data) > 1_048_576:
                raise DeliveryError(signal + "_response_too_large")
            body = json.loads(data) if data else {}
            if not isinstance(body, dict):
                raise ValueError()
            partial = body.get("partialSuccess", {})
            if not isinstance(partial, dict):
                raise ValueError()
            if int(partial.get(rejected, 0)) or partial.get("errorMessage"):
                raise DeliveryError(signal + "_partial_success")
        except HTTPError as error:
            raise DeliveryError(f"{signal}_http_{error.code}") from None
        except (URLError, OSError):
            raise DeliveryError(signal + "_connection_failure") from None
        except (ValueError, TypeError, OverflowError) as error:
            if isinstance(error, DeliveryError):
                raise
            raise DeliveryError(signal + "_invalid_response") from None
        delivered.append(signal)
    return delivered
