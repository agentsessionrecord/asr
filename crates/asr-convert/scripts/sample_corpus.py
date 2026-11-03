"""Bounded private history qualification with censored conversion timings."""
import collections
import concurrent.futures
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

BOUNDS = (16 * 1024, 128 * 1024, 1024 * 1024, 16 * 1024 * 1024, 128 * 1024 * 1024)
LABELS = ('under-16-KiB', '16-to-128-KiB', '128-KiB-to-1-MiB',
          '1-to-16-MiB', '16-to-128-MiB', 'at-least-128-MiB')


def stratum(size):
    return next((index for index, bound in enumerate(BOUNDS) if size < bound), len(BOUNDS))


def select(candidates, limit=300):
    """Include the ten largest, then balance deterministic choices across size bins."""
    ordered = sorted(candidates, key=lambda item: (-item['bytes'], item['path']))
    chosen = ordered[:min(10, limit)]
    selected = {item['path'] for item in chosen}
    bins = [[] for _ in LABELS]
    for item in ordered:
        if item['path'] not in selected:
            bins[stratum(item['bytes'])].append(item)
    for group in bins:
        group.sort(key=lambda item: hashlib.sha256(os.fsencode(item['path'])).digest())
    while len(chosen) < limit:
        added = False
        for group in bins:
            if group and len(chosen) < limit:
                chosen.append(group.pop())
                added = True
        if not added:
            break
    return chosen


def catalog(roots, limit):
    candidates = collections.defaultdict(list)
    seen = collections.defaultdict(set)
    inventory = collections.defaultdict(collections.Counter)
    for selection in roots:
        agent, root = selection.split('=', 1)
        for directory, _, names in os.walk(root, followlinks=False):
            for name in names:
                if not name.endswith(('.jsonl', '.jsonl.zst', '.jsonl.zstd')):
                    continue
                path = Path(directory, name)
                group = inventory[agent]
                group['candidate_entries'] += 1
                try:
                    stat = path.stat()
                except OSError:
                    group['unavailable_entries'] += 1
                    continue
                if not path.is_file():
                    continue
                if name.endswith(('.zst', '.zstd')) and path.with_suffix('').is_file():
                    group['compressed_companions'] += 1
                    continue
                identity = (stat.st_dev, stat.st_ino)
                if identity in seen[agent]:
                    group['file_aliases'] += 1
                    continue
                seen[agent].add(identity)
                candidates[agent].append({'path': str(path), 'bytes': stat.st_size})
    files = []
    for agent, values in sorted(candidates.items()):
        inventory[agent]['eligible_files'] = len(values)
        for index, item in enumerate(select(values, limit), 1):
            files.append({**item, 'agent': agent, 'id': f'{agent}-{index:03}',
                          'size_stratum': LABELS[stratum(item['bytes'])],
                          'largest_ten': index <= min(10, limit, len(values))})
    return {'roots': roots, 'limit_per_agent': limit, 'size_basis': 'stored file bytes',
            'inventory': inventory, 'files': files}


def write_json(path, value):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf8', dir=path.parent,
                                     prefix='.checkpoint-', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def run_command(command, timeout):
    start = time.monotonic()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        output, _ = process.communicate(timeout=max(0.001, timeout))
        return process.returncode, output, time.monotonic() - start
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        return None, b'', time.monotonic() - start


def check_file(item, binary, validator, out, timeout):
    destination = out/item['id']
    entry = {key: item[key] for key in ('id', 'agent', 'bytes', 'size_stratum', 'largest_ten')}
    exit_code, output, elapsed = run_command(
        [str(binary.resolve()), 'convert', '--agent', item['agent'], item['path'], '--out', str(destination)], timeout)
    entry.update(conversion_exit=exit_code, conversion_seconds=elapsed)
    if exit_code is None:
        entry['status'] = 'conversion_timeout'
    elif exit_code not in (0, 1):
        entry['status'] = 'conversion_failed'
    else:
        try:
            entry['conversion'] = json.loads(output)
        except ValueError:
            entry['status'] = 'conversion_summary_failed'
        else:
            if exit_code == 1:
                entry['status'] = 'no_session'
            elif elapsed >= timeout:
                entry['status'] = 'validation_timeout'
            else:
                checked, output, validation_time = run_command(
                    ['node', str(validator.resolve()), '--summary', '--json', str(destination)], timeout - elapsed)
                entry.update(validation_exit=checked, validation_seconds=validation_time)
                if checked is None:
                    entry['status'] = 'validation_timeout'
                else:
                    try:
                        value = json.loads(output)
                        entry['validation'] = {key: value[key] for key in
                                               ('valid', 'files', 'records', 'errors', 'warnings', 'inputFailures', 'counts')}
                        entry['status'] = 'passed' if checked == 0 else 'validation_failed'
                    except (ValueError, KeyError):
                        entry['status'] = 'validation_summary_failed'
    if entry['status'] != 'passed':
        # A killed conversion can leave an incomplete staging database or file.
        shutil.rmtree(destination, ignore_errors=True)
    return entry


def percentiles(values):
    values = sorted(values)
    if not values:
        return {}
    return {name: values[min(len(values) - 1, math.ceil(fraction * len(values)) - 1)]
            for name, fraction in [('p50', .5), ('p90', .9), ('p95', .95), ('p99', .99), ('max', 1)]}


def summarize(manifest, results, timeout):
    groups = {}
    codes = collections.Counter()
    diagnostics = collections.Counter()
    for agent in sorted({item['agent'] for item in manifest['files']}):
        entries = [entry for entry in results.values() if entry['agent'] == agent]
        totals = collections.Counter()
        for entry in entries:
            totals[entry['status']] += 1
            for key in ('files', 'records', 'errors', 'warnings', 'inputFailures'):
                totals['validation_' + key] += entry.get('validation', {}).get(key, 0)
            codes.update(entry.get('validation', {}).get('counts', {}))
            diagnostics.update(entry.get('conversion', {}).get('diagnostics', {}))
        completed = [entry['conversion_seconds'] for entry in entries if entry['conversion_exit'] is not None]
        groups[agent] = {'attempted': len(entries), 'totals': totals,
                         'observed_conversion_seconds': percentiles([entry['conversion_seconds'] for entry in entries]),
                         'completed_conversion_seconds': percentiles(completed),
                         'conversion_timeouts': sum(entry['conversion_exit'] is None for entry in entries),
                         'slowest': sorted(entries, key=lambda entry: entry['conversion_seconds'], reverse=True)[:10]}
    return {'timeout_seconds': timeout, 'size_basis': manifest['size_basis'],
            'by_agent': groups, 'validation_codes': codes, 'conversion_codes': diagnostics}


def run(args):
    os.umask(0o077)
    args.out.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(args.out, 0o700)
    manifest_path = args.out/'sample-catalog.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest['roots'] != args.root or manifest['limit_per_agent'] != args.limit:
            raise ValueError('use a fresh output directory for a different sample')
    else:
        manifest = catalog(args.root, args.limit)
        write_json(manifest_path, manifest)
    results_path = args.out/'sample-counts.json'
    results = json.loads(results_path.read_text()) if results_path.exists() else {}
    pending = [item for item in manifest['files'] if item['id'] not in results]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = [executor.submit(check_file, item, args.binary, args.validator, args.out, args.timeout_seconds)
                   for item in pending]
        for future in concurrent.futures.as_completed(futures):
            entry = future.result()
            results[entry['id']] = entry
            write_json(results_path, results)
            print(json.dumps({'file': entry['id'], 'status': entry['status'],
                              'completed': len(results), 'selected': len(manifest['files'])}), flush=True)
    summary = summarize(manifest, results, args.timeout_seconds)
    write_json(args.out/'sample-summary.json', summary)
    print(json.dumps({'completed': len(results), 'statuses': dict(collections.Counter(
        entry['status'] for entry in results.values()))}), flush=True)
    return int(any(entry['status'] != 'passed' for entry in results.values()))
