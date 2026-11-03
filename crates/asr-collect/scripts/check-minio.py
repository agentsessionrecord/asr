#!/usr/bin/env python3
"""Exercise real multipart S3 uploads in one owned disposable MinIO container."""
import argparse
import datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


def sign_request(endpoint, access, secret, method, path, query='', body=b''):
    now = datetime.datetime.now(datetime.timezone.utc)
    date, stamp = now.strftime('%Y%m%d'), now.strftime('%Y%m%dT%H%M%SZ')
    host = urllib.parse.urlsplit(endpoint).netloc
    payload = hashlib.sha256(body).hexdigest()
    headers = {'host': host, 'x-amz-content-sha256': payload, 'x-amz-date': stamp}
    names = ';'.join(sorted(headers))
    canonical = '\n'.join([method, path, query,
        ''.join(f'{name}:{headers[name]}\n' for name in sorted(headers)), names, payload])
    scope = f'{date}/us-east-1/s3/aws4_request'
    string = '\n'.join(['AWS4-HMAC-SHA256', stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    key = ('AWS4' + secret).encode()
    for component in (date, 'us-east-1', 's3', 'aws4_request'):
        key = hmac.new(key, component.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, string.encode(), hashlib.sha256).hexdigest()
    headers['Authorization'] = f'AWS4-HMAC-SHA256 Credential={access}/{scope}, SignedHeaders={names}, Signature={signature}'
    request = urllib.request.Request(endpoint + path + ('?' + query if query else ''),
                                     data=body if method == 'PUT' else None, headers=headers, method=method)
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=30)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--image', required=True, help='A local MinIO image. No implicit pull.')
    parser.add_argument('--sudo', action='store_true')
    args = parser.parse_args()
    binary = args.binary.resolve()
    docker = (['sudo', '-n'] if args.sudo else []) + ['docker']
    container = None
    with tempfile.TemporaryDirectory(prefix='asr-minio-check-') as directory:
        root = Path(directory)
        access, secret = 'synthetic-' + secrets.token_hex(8), secrets.token_hex(32)
        credentials = root / 'runtime.env'
        credentials.write_text(f'MINIO_ROOT_USER={access}\nMINIO_ROOT_PASSWORD={secret}\n')
        credentials.chmod(0o600)
        try:
            run = subprocess.run(docker + ['run', '--pull=never', '--detach', '--rm',
                '--name', 'asr-synthetic-' + secrets.token_hex(5), '--env-file', str(credentials),
                '--publish', '127.0.0.1::9000', args.image, 'server', '/data', '--address', ':9000'],
                capture_output=True, check=True, timeout=30)
            container = run.stdout.decode().strip()
            port = subprocess.run(docker + ['inspect', '--format',
                '{{(index (index .NetworkSettings.Ports "9000/tcp") 0).HostPort}}', container],
                capture_output=True, check=True, timeout=10).stdout.decode().strip()
            endpoint = 'http://127.0.0.1:' + port
            deadline = time.monotonic() + 30
            while True:
                try:
                    with urllib.request.urlopen(endpoint + '/minio/health/live', timeout=1) as response:
                        assert response.status == 200
                    break
                except (OSError, AssertionError):
                    if time.monotonic() > deadline:
                        raise AssertionError('owned MinIO container did not become ready') from None
                    time.sleep(0.1)
            with sign_request(endpoint, access, secret, 'PUT', '/asr-synthetic') as response:
                assert response.status == 200
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith(('AWS_', 'GOOGLE_', 'AZURE_'))}
            env.update({'AWS_ENDPOINT': endpoint, 'AWS_ALLOW_HTTP': 'true', 'AWS_ACCESS_KEY_ID': access,
                'AWS_SECRET_ACCESS_KEY': secret, 'AWS_REGION': 'us-east-1', 'AWS_DEFAULT_REGION': 'us-east-1',
                'AWS_VIRTUAL_HOSTED_STYLE_REQUEST': 'false', 'AWS_EC2_METADATA_DISABLED': 'true',
                'NO_PROXY': '127.0.0.1,localhost', 'no_proxy': '127.0.0.1,localhost'})
            native = root / 'native.jsonl'
            text = 'synthetic content ' * (9 * 1024 * 1024 // len('synthetic content '))
            native.write_text(json.dumps({'sessionId': 'multipart-session', 'uuid': 'prompt',
                'type': 'user', 'message': {'role': 'user', 'content': text}}) + '\n')
            state = root / 'state'
            command = [str(binary), 'collect', '--source', f'claude-code={native}', '--target',
                's3://asr-synthetic/prefix', '--state', str(state), '--machine', 'synthetic-machine',
                '--uploader', 'synthetic-uploader', '--window-seconds', '1']
            first = subprocess.run(command, env=env, capture_output=True, check=True, timeout=60)
            assert json.loads(first.stdout)['uploaded_sessions'] == 1
            time.sleep(1.1)
            second = subprocess.run(command, env=env, capture_output=True, check=True, timeout=60)
            assert json.loads(second.stdout)['converted_sessions'] == 0
            with sign_request(endpoint, access, secret, 'GET', '/asr-synthetic', 'list-type=2') as response:
                listing = ET.fromstring(response.read())
            keys = [element.text for element in listing.findall('.//{*}Key')]
            objects, manifests = [], []
            for key in keys:
                assert key.startswith('prefix/') and '%' not in key
                with sign_request(endpoint, access, secret, 'GET', '/asr-synthetic/' + key) as response:
                    content = response.read()
                    assert response.headers['x-amz-meta-sha256'] == hashlib.sha256(content).hexdigest()
                if key.endswith('.jsonl'):
                    assert len(content) > 8 * 1024 * 1024
                    assert key.rsplit('/', 1)[1][:-6] == hashlib.sha256(content).hexdigest()
                    objects.append(content)
                else:
                    assert key.endswith('.manifest.json')
                    manifest = json.loads(content)
                    for entry in manifest['entries']:
                        assert entry['status'] == 'received'
                    manifests.append(manifest)
                local = root / ('download-' + key.rsplit('/', 1)[1])
                local.write_bytes(content)
                validation = subprocess.run([str(binary), 'validate', '--json', '--summary', str(local)],
                    capture_output=True, check=True, timeout=30)
                assert json.loads(validation.stdout)['errors'] == 0
            assert len(objects) == 1 and len(manifests) >= 1
            entries = [entry for manifest in manifests for entry in manifest['entries']]
            assert len(entries) == 1
            assert entries[0]['sha256'] == hashlib.sha256(objects[0]).hexdigest()
            assert entries[0]['byteLength'] == len(objects[0])
            assert not list((state / 'receipts' / 'objects').glob('*.jsonl'))
            expected = root / 'expected'
            subprocess.run([str(binary), 'convert', '--agent', 'claude-code', str(native), '--out', str(expected)],
                           capture_output=True, check=True, timeout=60)
            expected_files = list(expected.glob('*.jsonl'))
            assert len(expected_files) == 1 and expected_files[0].read_bytes() == objects[0]
            print(json.dumps({'minio': 'passed', 'multipart_objects': len(objects), 'manifests': len(manifests),
                'exact_bytes': 'passed', 'sha256_metadata': 'passed', 'unchanged_retry': 'passed', 'validator_errors': 0}))
        finally:
            if container is not None:
                subprocess.run(docker + ['rm', '--force', container], capture_output=True, check=True, timeout=15)
                # The owned container must be gone, even after a failed assertion.
                remaining = subprocess.run(docker + ['ps', '--all', '--quiet', '--filter', 'id=' + container],
                    capture_output=True, check=True, timeout=10)
                assert not remaining.stdout.strip()
            credentials.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
