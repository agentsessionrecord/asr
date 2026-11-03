"""Private, bounded database qualification using the shared corpus sampler."""
import collections
import json
import os
from pathlib import Path
import shutil
import time

from sample_corpus import LABELS, run_command, select, stratum, write_json

AGENTS = ('astrbot', 'crush', 'lingma', 'shelley', 'deepagents', 'forgecode',
          'opencode', 'kilo', 'mimocode', 'zed', 'devin', 'firebender', 'goose',
          'kiro', 'warp', 'openclaw')


def catalog(roots, limit):
    candidates = collections.defaultdict(list)
    seen = collections.defaultdict(set)
    inventory = {agent: collections.Counter() for agent in AGENTS}
    for selection in roots:
        agent, root = selection.split('=', 1)
        if agent not in AGENTS:
            raise ValueError('unsupported database agent')
        root = Path(root)
        paths = [root] if root.is_file() else (
            Path(directory, name) for directory, _, names in os.walk(root, followlinks=False)
            for name in names)
        for path in paths:
            if path.suffix not in ('.db', '.sqlite', '.sqlite3', '.vscdb') and not (
                    agent == 'openclaw' and path.suffix == '.jsonl'):
                continue
            # Prefer the native store over adjacent migration transcripts.
            if agent == 'openclaw' and path.suffix == '.jsonl' and (
                    path.parent.parent/'agent/openclaw-agent.sqlite').is_file():
                inventory[agent]['migration_companions'] += 1
                continue
            inventory[agent]['candidate_entries'] += 1
            try:
                stat = path.stat()
            except OSError:
                inventory[agent]['unavailable_entries'] += 1
                continue
            if not path.is_file():
                continue
            identity = (stat.st_dev, stat.st_ino)
            if identity in seen[agent]:
                inventory[agent]['file_aliases'] += 1
                continue
            seen[agent].add(identity)
            candidates[agent].append({'path': str(path.resolve()), 'bytes': stat.st_size})
    files = []
    for agent in AGENTS:
        inventory[agent]['eligible_files'] = len(candidates[agent])
        for index, item in enumerate(select(candidates[agent], limit), 1):
            files.append({**item, 'agent': agent, 'id': f'{agent}-{index:03}',
                          'size_stratum': LABELS[stratum(item['bytes'])]})
    return {'roots': roots, 'limit_per_agent': limit, 'inventory': inventory, 'files': files}


def check_file(item, binary, validator, out, timeout, namespaces):
    destination = out/item['id']
    entry = {key: item[key] for key in ('id', 'agent', 'bytes', 'size_stratum')}
    command = [str(binary.resolve()), 'convert', '--agent', item['agent'], item['path'],
               '--out', str(destination)]
    if item['agent'] in namespaces:
        command += ['--namespace', namespaces[item['agent']]]
    start = time.monotonic()
    code, output, elapsed = run_command(command, timeout)
    entry.update(conversion_exit=code, conversion_seconds=elapsed)
    if code is None:
        entry['status'] = 'conversion_timeout'
    elif code not in (0, 1):
        entry['status'] = 'conversion_failed'
    else:
        try:
            conversion = json.loads(output)
            # Keep only reviewed counts. No source strings or diagnostic messages.
            entry['conversion'] = {key: conversion[key] for key in
                                   ('files', 'sessions', 'records', 'source_bytes', 'diagnostics')}
            if code == 1:
                entry['status'] = 'no_session'
            else:
                remaining = timeout - (time.monotonic() - start)
                if remaining <= 0:
                    entry['status'] = 'validation_timeout'
                else:
                    checked, output, elapsed = run_command(
                        ['node', str(validator.resolve()), '--summary', '--json', str(destination)],
                        remaining)
                    entry.update(validation_exit=checked, validation_seconds=elapsed)
                    if checked is None:
                        entry['status'] = 'validation_timeout'
                    else:
                        value = json.loads(output)
                        entry['validation'] = {key: value[key] for key in
                                               ('files', 'records', 'errors', 'warnings', 'counts')}
                        entry['status'] = 'passed' if checked == 0 else 'validation_failed'
        except (ValueError, KeyError, TypeError):
            entry['status'] = 'summary_failed'
    if entry['status'] != 'passed':
        shutil.rmtree(destination, ignore_errors=True)
    return entry


def summarize(manifest, results):
    groups = {}
    for agent in AGENTS:
        entries = [r for r in results.values() if r['agent'] == agent]
        codes = collections.Counter()
        diagnostics = collections.Counter()
        totals = collections.Counter()
        for entry in entries:
            totals[entry['status']] += 1
            conversion = entry.get('conversion', {})
            for key in ('sessions', 'records'):
                totals[key] += conversion.get(key, 0)
            diagnostics.update(conversion.get('diagnostics', {}))
            codes.update(entry.get('validation', {}).get('counts', {}))
        groups[agent] = {'eligible_files': manifest['inventory'][agent]['eligible_files'],
                         'attempted_files': len(entries), 'totals': totals,
                         'conversion_codes': diagnostics, 'validation_codes': codes}
    return {'by_agent': groups}


def run(args):
    os.umask(0o077)
    args.out.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(args.out, 0o700)
    manifest = catalog(args.root, args.limit)
    write_json(args.out/'sample-catalog.json', manifest)
    namespaces = dict(value.split('=', 1) for value in args.namespace)
    results = {}
    for item in manifest['files']:
        entry = check_file(item, args.binary, args.validator, args.out,
                           args.timeout_seconds, namespaces)
        results[item['id']] = entry
        write_json(args.out/'sample-counts.json', results)
        print(json.dumps({'file': item['id'], 'status': entry['status']}), flush=True)
    summary = summarize(manifest, results)
    write_json(args.out/'sample-summary.json', summary)
    print(json.dumps(summary), flush=True)
    return int(any(r['status'] != 'passed' for r in results.values()))
