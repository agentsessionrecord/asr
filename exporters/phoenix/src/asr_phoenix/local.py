"""Explicit local Phoenix import. Destinations never come from stream data."""

import argparse
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("redirect_refused")


def local_url(endpoint):
    parsed = urlsplit(endpoint)
    try:
        loopback = parsed.hostname in ("127.0.0.1", "::1") and ip_address(parsed.hostname).is_loopback
    except ValueError:
        loopback = False
    if not loopback or parsed.scheme != "http" or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("literal_loopback_http_endpoint_required")
    return endpoint.rstrip("/")


def load(endpoint, directory):
    base = local_url(endpoint)
    opener = build_opener(ProxyHandler({}), NoRedirect())
    results = []
    for name, route, media in (("traces.otlp.pb", "/v1/traces", "application/x-protobuf"),
                               ("dataset-upload.json", "/v1/datasets/upload", "application/json")):
        request = Request(base + route, data=(Path(directory) / name).read_bytes(), headers={"Content-Type": media}, method="POST")
        with opener.open(request, timeout=30) as response:
            results.append(response.status)
    return results


def main():
    parser = argparse.ArgumentParser(description="Import offline files into a loopback Phoenix instance.")
    parser.add_argument("directory")
    parser.add_argument("--endpoint", required=True)
    args = parser.parse_args()
    try:
        statuses = load(args.endpoint, args.directory)
    except (OSError, ValueError):
        print("local_import_failed")
        return 1
    print("local_import_statuses=" + ",".join(map(str, statuses)))
    return 0
