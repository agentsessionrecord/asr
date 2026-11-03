#!/usr/bin/env python3
"""Bounded CLI checks. All data is synthetic and all processes are owned here."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time


def stop(process):
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def wait_for(predicate, process, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError('owned service exited before its expected result')
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError('owned service did not produce its expected result in time')


def native(path, text, item='item-1', mode='w'):
    with path.open(mode) as output:
        output.write(json.dumps({'sessionId': 'synthetic-session', 'uuid': item,
                                 'type': 'user', 'message': {'role': 'user', 'content': text}}) + '\n')


def checkpoint(state, count):
    try:
        saved = json.loads((state / 'state.json').read_text())
        return len(saved['sessions']) == count
    except (OSError, ValueError):
        return False


def run(binary, root, poll_only):
    source = root / 'input'
    source.mkdir()
    native(source / 'first.jsonl', 'First synthetic message.')
    state, target = root / 'state', root / 'target'
    command = [str(binary), 'collect', '--source', f'claude-code={source}', '--target', str(target),
               '--state', str(state), '--machine', 'synthetic-machine', '--uploader', 'synthetic-uploader',
               '--window-seconds', '1', '--watch', '--poll-seconds', '1' if poll_only else '30']
    if poll_only:
        command.append('--poll-only')
    with (root / 'watch.log').open('wb') as log:
        process = subprocess.Popen(command, stdout=log, stderr=log)
        try:
            wait_for(lambda: checkpoint(state, 1), process)
            old = json.loads((state / 'state.json').read_text())['sessions']['claude-code:synthetic-session']['sha256']
            native(source / 'first.jsonl', 'Second synthetic message.', 'item-2', 'a')
            def changed():
                try:
                    saved = json.loads((state / 'state.json').read_text())
                    return saved['sessions']['claude-code:synthetic-session']['sha256'] != old
                except (OSError, KeyError, ValueError):
                    return False
            # The event test must finish before its 30 second polling fallback.
            wait_for(changed, process, 10)
            (source / 'new.jsonl').write_text(json.dumps({'sessionId': 'new-session', 'uuid': 'new-item',
                'type': 'user', 'message': {'role': 'user', 'content': 'New synthetic session.'}}) + '\n')
            wait_for(lambda: checkpoint(state, 2), process, 10)
            wait_for(lambda: len(list(target.rglob('*.manifest.json'))) >= 1, process)
            # Retry state remains readable after a process stop.
            saved = json.loads((state / 'state.json').read_text())
            assert len(saved['sessions']) == 2
        finally:
            stop(process)
    for path in target.glob('objects/*.jsonl'):
        assert path.stem == hashlib.sha256(path.read_bytes()).hexdigest()
    result = subprocess.run([str(binary), 'validate', '--json', '--summary', str(target)],
                            capture_output=True, check=True, timeout=30)
    assert json.loads(result.stdout)['errors'] == 0
    result = subprocess.run(command[:command.index('--watch')], capture_output=True, check=True, timeout=30)
    assert json.loads(result.stdout)['converted_sessions'] == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    args = parser.parse_args()
    binary = args.binary.resolve()
    with tempfile.TemporaryDirectory(prefix='asr-local-check-') as directory:
        root = Path(directory)
        for mode in (False, True):
            work = root / ('poll' if mode else 'events')
            work.mkdir()
            run(binary, work, mode)
    print(json.dumps({'file_events': 'passed', 'polling': 'passed', 'new_sessions': 'passed',
                      'restart': 'passed', 'digest_checks': 'passed', 'validator_errors': 0}))


if __name__ == '__main__':
    main()
