#!/usr/bin/env python3
"""Bounded private qualification for document and mailbox adapters."""
import argparse
import collections
import json
import os
from pathlib import Path
import time
from sample_corpus import check_file, select, stratum, LABELS, write_json

AGENTS = ('auggie', 'cline', 'codebuddy', 'continue', 'hermes', 'nanoclaw',
          'openhands', 'roo-code', 'rovodev')


def defaults(home):
    roots = {
        'auggie': [home/'.augment/sessions'],
        'cline': [home/'.cline/data'],
        'codebuddy': [home/'.codebuddy'],
        'continue': [home/'.continue/sessions'],
        'hermes': [home/'.hermes'],
        'nanoclaw': [home/'nanoclaw', home/'code/nanoclaw'],
        'openhands': [home/'.openhands/conversations', home/'.openhands/v1_conversations'],
        'roo-code': [],
        'rovodev': [home/'.rovodev/sessions'],
    }
    for editor in ('Code', 'Code - Insiders', 'VSCodium', 'Cursor', 'Windsurf'):
        base = home/'.config'/editor/'User'
        stores = [base/'globalStorage']
        profiles = base/'profiles'
        if profiles.is_dir():
            stores.extend(p/'globalStorage' for p in profiles.iterdir() if p.is_dir() and not p.is_symlink())
        for store in stores:
            roots['cline'].append(store/'saoudrizwan.claude-dev/tasks')
            for extension in ('rooveterinaryinc.roo-cline', 'rooveterinaryinc.roo-code-nightly'):
                roots['roo-code'].append(store/extension/'tasks')
    for agent, name in [('hermes', 'HERMES_HOME'), ('codebuddy', 'CODEBUDDY_HOME'),
                        ('continue', 'CONTINUE_GLOBAL_DIR'), ('rovodev', 'ROVODEV_SESSION_DIR')]:
        value = os.environ.get(name)
        if value:
            roots[agent].insert(0, Path(value))
    return roots


def selected(agent, path):
    name = path.name
    if agent == 'hermes':
        return name == 'state.db'
    if agent == 'nanoclaw':
        return name == 'v2.db'
    if agent == 'codebuddy':
        return name.endswith('.jsonl') or name == 'index.json' and (path.parent/'messages').is_dir()
    if agent in ('cline', 'roo-code'):
        return name in ('api_conversation_history.json', 'claude_messages.json', 'ui_messages.json') or name.endswith('.messages.json')
    if agent == 'openhands':
        return name.endswith('.json') and (path.parent.name == 'events' or name.startswith('event-') and path.parent.parent.name == 'v1_conversations')
    if agent == 'rovodev':
        return name == 'session_context.json'
    return name.endswith('.json')


def catalog(roots, limit):
    inventory = {}
    files = []
    for agent in AGENTS:
        candidates = []
        seen = set()
        for root in roots.get(agent, []):
            if root.is_file():
                paths = [root]
            else:
                paths = (Path(directory, name) for directory, dirs, names in os.walk(root, followlinks=False)
                         for name in names)
            for path in paths:
                if not selected(agent, path) or not path.is_file() or path.is_symlink():
                    continue
                stat = path.stat()
                identity = (stat.st_dev, stat.st_ino)
                if identity in seen:
                    continue
                seen.add(identity)
                candidates.append({'path': str(path), 'bytes': stat.st_size})
        inventory[agent] = {'eligible_files': len(candidates)}
        for index, item in enumerate(select(candidates, limit), 1):
            files.append({**item, 'id': f'{agent}-{index:03}', 'agent': agent,
                          'size_stratum': LABELS[stratum(item['bytes'])],
                          'largest_ten': index <= min(10, limit, len(candidates))})
    return {'roots': {agent: [str(p) for p in paths] for agent, paths in roots.items()},
            'limit_per_agent': limit, 'inventory': inventory, 'files': files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--validator', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--root', action='append', default=[], help='Add an agent=directory root')
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--timeout-seconds', type=float, default=300)
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 100 or args.timeout_seconds <= 0 or args.timeout_seconds > 300:
        parser.error('limits must be 1..100 files and 0..300 seconds per agent')
    os.umask(0o077)
    args.out.mkdir(mode=0o700, parents=True, exist_ok=True)
    args.out.chmod(0o700)
    roots = defaults(Path.home())
    for root in args.root:
        agent, value = root.split('=', 1)
        if agent not in AGENTS:
            parser.error('unsupported agent root')
        roots[agent].append(Path(value))
    manifest = catalog(roots, args.limit)
    write_json(args.out/'sample-catalog.json', manifest)
    results = {}
    summary = {}
    for agent in AGENTS:
        deadline = time.monotonic() + args.timeout_seconds
        entries = []
        for item in manifest['files']:
            if item['agent'] != agent:
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                result = {'id': item['id'], 'agent': agent, 'status': 'agent_budget_exhausted'}
            else:
                result = check_file(item, args.binary, args.validator, args.out, remaining)
            results[item['id']] = result
            entries.append(result)
            write_json(args.out/'sample-counts.json', results)
        diagnostics = collections.Counter()
        validation = collections.Counter()
        totals = collections.Counter()
        for result in entries:
            totals[result['status']] += 1
            diagnostics.update(result.get('conversion', {}).get('diagnostics', {}))
            validation.update(result.get('validation', {}).get('counts', {}))
            for key in ('records', 'errors', 'warnings'):
                totals[key] += result.get('validation', {}).get(key, 0)
        summary[agent] = {'eligible': manifest['inventory'][agent]['eligible_files'],
                          'selected': len(entries), 'totals': dict(totals),
                          'conversion_diagnostics': dict(diagnostics),
                          'validation_diagnostics': dict(validation)}
    write_json(args.out/'sample-counts.json', results)
    write_json(args.out/'sample-summary.json', summary)
    print(json.dumps(summary, indent=2))
    return int(any(result['status'] != 'passed' for result in results.values()))


if __name__ == '__main__':
    raise SystemExit(main())
