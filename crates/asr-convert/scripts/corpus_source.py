"""Group corpus files by recorded identity without retaining transcript bodies."""
import collections
import contextlib
import json
from pathlib import Path
import re
import subprocess

LIMIT = 16 * 1024 * 1024
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I)


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate key')
        value[key] = item
    return value


@contextlib.contextmanager
def reader(path):
    if path.name.endswith(('.zst', '.zstd')):
        process = subprocess.Popen(['zstd', '-q', '-d', '-c', '--', str(path)],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            yield process.stdout
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.terminate()
            process.wait()
    else:
        with path.open('rb') as stream:
            yield stream


def identity(agent, path):
    hint = None
    for candidate in [path, path.resolve()]:
        if candidate.name.startswith('rollout-'):
            match = UUID.search(candidate.name)
            if match:
                hint = match[0]
                break
    first = None
    ambiguous = False
    with reader(path) as stream:
        while True:
            line = stream.readline(LIMIT + 1)
            if not line:
                break
            if len(line) > LIMIT:
                while line and not line.endswith(b'\n'):
                    line = stream.readline(LIMIT + 1)
                continue
            if not line.endswith(b'\n'):
                break
            # Native metadata uses this literal type. Escaped keys or values
            # still take the full parser path. Other transcript bodies stay opaque.
            if agent == 'codex' and b'session_meta' not in line and b'\\u' not in line:
                continue
            try:
                value = json.loads(line, object_pairs_hook=unique)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(value, dict):
                continue
            if agent == 'codex':
                if value.get('type') != 'session_meta':
                    continue
                payload = value.get('payload')
                if not isinstance(payload, dict):
                    continue
                candidate = payload.get('id')
                if isinstance(candidate, str) and candidate:
                    if first is None:
                        first = candidate
                    elif first != candidate:
                        ambiguous = True
                    if hint == candidate:
                        return candidate
                continue
            else:
                candidates = [value.get('agentId'), value.get('sessionId')]
            for candidate in candidates:
                if isinstance(candidate, str) and candidate:
                    return candidate
    return None if ambiguous else first


def partition(agent, directory, files, target):
    groups = collections.OrderedDict()
    unknown = []
    for name in files:
        native = identity(agent, Path(directory, name))
        if native is None:
            unknown.append(name)
        else:
            groups.setdefault(native, []).append(name)
    if not groups:
        return [files]
    # An unidentified file contributes diagnostics without becoming a fabricated
    # session or causing a standalone no-session conversion failure.
    next(iter(groups.values())).extend(unknown)
    chunks = []
    current = []
    for group in groups.values():
        if current and len(current) + len(group) > target:
            chunks.append(current)
            current = []
        current.extend(group)
    if current:
        chunks.append(current)
    return chunks
