"""Explicit local endpoints only. Stream values never select a destination."""

import http.client
import ipaddress
import math
import subprocess
from urllib.parse import urlsplit

from .reader import SearchError, dumps, loads, valid_index


class LocalHTTP:
    def __init__(self, endpoint):
        try:
            parsed = urlsplit(endpoint)
            host, port = parsed.hostname, parsed.port
            local = host == "localhost" or (host is not None and ipaddress.ip_address(host).is_loopback)
        except ValueError:
            raise SearchError("endpoint_must_be_loopback") from None
        if (not local or parsed.scheme not in ("http", "https") or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or parsed.path not in ("", "/")):
            raise SearchError("endpoint_must_be_loopback")
        self.scheme, self.host, self.port = parsed.scheme, host, port

    def request(self, method, path, body=None, content_type="application/json", allow_missing=False):
        connection_type = http.client.HTTPSConnection if self.scheme == "https" else http.client.HTTPConnection
        connection = connection_type(self.host, self.port, timeout=30)
        data = body if isinstance(body, bytes) else (dumps(body).encode() if body is not None else None)
        try:
            connection.request(method, path, data, {"Content-Type": content_type})
            response = connection.getresponse()
            status = response.status
            raw = response.read(8 * 1024 * 1024 + 1)
            if status == 404 and allow_missing:
                return status, {}
            if not 200 <= status < 300:
                raise SearchError(f"http_status_{status}")
            if len(raw) > 8 * 1024 * 1024:
                raise SearchError("http_response_too_large")
            try:
                result = loads(raw)
            except (ValueError, UnicodeError, RecursionError):
                raise SearchError("invalid_http_json") from None
            if not isinstance(result, dict):
                raise SearchError("invalid_http_response")
            if result.get("status") == "error" or "error" in result:
                raise SearchError("database_reported_error")
            return status, result
        except (OSError, http.client.HTTPException):
            raise SearchError("local_http_transport_failed") from None
        finally:
            connection.close()


def embed(command, texts, dimensions):
    if (not isinstance(command, list) or not command
            or not all(isinstance(arg, str) and arg for arg in command)):
        raise SearchError("embedding_command_must_be_argv")
    try:
        process = subprocess.run(command, input=dumps({"texts": texts}), text=True,
                                 capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        raise SearchError("embedding_command_failed") from None
    if process.returncode:
        raise SearchError("embedding_command_failed")
    try:
        response = loads(process.stdout)
        vectors = response["vectors"]
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise ValueError
        result = []
        for vector in vectors:
            if not isinstance(vector, list) or len(vector) != dimensions:
                raise ValueError
            values = []
            for value in vector:
                if isinstance(value, (bool, str, dict, list)) or value is None:
                    raise ValueError
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError
                values.append(number)
            result.append(values)
        return result
    except (ValueError, TypeError, KeyError, OverflowError):
        raise SearchError("invalid_embedding_response") from None


def load_search(client, index, mapping, records, batch_size=200, max_batch_bytes=5 * 1024 * 1024):
    valid_index(index)
    status, existing = client.request("GET", "/" + index, allow_missing=True)
    if status == 404:
        client.request("PUT", "/" + index, mapping)
    elif _mapping_shape(existing.get(index, {}).get("mappings", {})) != _mapping_shape(mapping["mappings"]):
        raise SearchError("existing_index_mapping_differs")
    count, batch, size = 0, [], 0

    def send():
        nonlocal count, batch, size
        if not batch:
            return
        _, result = client.request("POST", "/_bulk", b"".join(batch), "application/x-ndjson")
        items = result.get("items")
        if (result.get("errors") is not False or not isinstance(items, list) or len(items) != len(batch)
                or any(not 200 <= item.get("index", {}).get("status", 0) < 300 for item in items)):
            raise SearchError("bulk_item_failure")
        count += len(batch)
        batch, size = [], 0

    for record in records:
        action = {"index": {"_index": index, "_id": record["document_id"]}}
        data = (dumps(action) + "\n" + dumps(record) + "\n").encode()
        if len(data) > max_batch_bytes:
            raise SearchError("document_exceeds_bulk_byte_limit")
        if batch and (len(batch) >= batch_size or size + len(data) > max_batch_bytes):
            send()
        batch.append(data)
        size += len(data)
    send()
    client.request("POST", "/" + index + "/_refresh")
    return count


def _mapping_shape(value):
    if not isinstance(value, dict):
        return value
    # Search servers omit this redundant type when returning object mappings.
    return {key: _mapping_shape(item) for key, item in value.items()
            if not (key == "type" and item == "object" and ("properties" in value or "enabled" in value))}


def load_qdrant(client, collection, dimensions, chunks, batch_size=64):
    valid_index(collection)
    status, existing = client.request("GET", "/collections/" + collection, allow_missing=True)
    expected = {"size": dimensions, "distance": "Cosine"}
    if status == 404:
        client.request("PUT", "/collections/" + collection, {"vectors": expected})
    else:
        config = existing.get("result", {}).get("config", {}).get("params", {}).get("vectors")
        if config != expected:
            raise SearchError("existing_collection_vectors_differ")
    count, batch = 0, []

    def send():
        nonlocal count, batch
        if not batch:
            return
        _, response = client.request("PUT", "/collections/" + collection + "/points?wait=true", {"points": batch})
        if response.get("result", {}).get("status") != "completed":
            raise SearchError("qdrant_upsert_not_completed")
        count += len(batch)
        batch = []

    for chunk in chunks:
        vector = chunk.get("vector")
        if (not isinstance(vector, list) or len(vector) != dimensions
                or any(isinstance(v, (bool, str, list, dict)) or v is None
                       or not math.isfinite(float(v)) for v in vector)):
            raise SearchError("chunk_has_invalid_vector")
        payload = {key: value for key, value in chunk.items() if key != "vector"}
        batch.append({"id": chunk["chunk_id"], "vector": vector, "payload": payload})
        if len(batch) >= batch_size:
            send()
    send()
    return count
