"""Offline AI Gateway Logpush consumer. Never connects to Cloudflare."""
from __future__ import annotations

import argparse
import base64
import gzip
import json
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from asr_gateways.core import GatewayRecorder
from asr_gateways.cli import MAX_BODY


def decrypt(value, private_key=None):
    if isinstance(value, dict) and 'key' in value:
        if private_key is None:
            raise ValueError('Encrypted payload requires a private key file')
        decode = lambda field: base64.b64decode(value[field], validate=True)
        aes = private_key.decrypt(decode('key'), padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
        return AESGCM(aes).decrypt(decode('iv'), decode('data'), None).decode('utf-8')
    return value


def object_value(value):
    return json.loads(value) if isinstance(value, str) else value


def capture(recorder, payload, *, private_key=None):
    metadata = object_value(decrypt(payload.get('Metadata', {}), private_key))
    # Custom metadata explicitly carries original agent headers. Trace and log IDs are not session IDs.
    headers = metadata.get('asr_headers', {})
    if isinstance(headers, str):
        headers = json.loads(headers)
    api = metadata.get('asr_api')
    request = object_value(decrypt(payload['RequestBody'], private_key))
    response = decrypt(payload['ResponseBody'], private_key)
    return recorder.capture(api, headers, request, response, status=payload.get('ResponseStatus'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--input', required=True, help='Local Logpush JSONL or gzip file')
    parser.add_argument('--private-key-file', help='Private RSA PEM file, never copied into ASR')
    args = parser.parse_args()
    private_key = serialization.load_pem_private_key(Path(args.private_key_file).read_bytes(), password=None) if args.private_key_file else None
    recorder = GatewayRecorder(args.output, gateway='cloudflare', historical=True)
    try:
        opener = gzip.open if args.input.endswith('.gz') else open
        with opener(args.input, 'rt', encoding='utf-8') as stream:
            for line in iter(lambda: stream.readline(MAX_BODY + 1), ''):
                if len(line) > MAX_BODY:
                    recorder.skipped += 1
                    break
                try:
                    capture(recorder, json.loads(line), private_key=private_key)
                except (ValueError, KeyError, TypeError, InvalidTag):
                    recorder.skipped += 1
    finally:
        recorder.close()
    print(json.dumps({'accepted': recorder.accepted, 'skipped': recorder.skipped}))
    if recorder.skipped:
        raise SystemExit(1)
