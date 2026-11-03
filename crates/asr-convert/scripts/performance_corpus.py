"""Serial converter measurements and exact comparisons against retained exports."""
import collections
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from sample_corpus import percentiles, write_json


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def same_bytes(left, right):
    if left.stat().st_size != right.stat().st_size:
        return False
    with left.open('rb') as a, right.open('rb') as b:
        while True:
            chunk = a.read(1024 * 1024)
            if chunk != b.read(1024 * 1024):
                return False
            if not chunk:
                return True


def compare(destination, references, ident):
    actual = {p.name: p for p in destination.glob('*.jsonl')}
    if not actual:
        return 'output_missing'
    for root in references:
        for directory in (root/ident/'asr', root/ident):
            expected = {p.name: p for p in directory.glob('*.jsonl')}
            if expected:
                if actual.keys() != expected.keys():
                    return 'file_set_changed'
                return ('equal' if all(same_bytes(actual[name], expected[name])
                                       for name in actual) else 'bytes_changed')
    return 'reference_missing'


def measured(command, timeout, profile=False):
    """GNU time measures this child only. A deadline kills its owned process group."""
    with tempfile.TemporaryDirectory(prefix='asr-perf-') as scratch:
        metrics = Path(scratch)/'metrics'
        env = dict(os.environ)
        if profile:
            env['ASR_CONVERT_PROFILE'] = '1'
        else:
            env.pop('ASR_CONVERT_PROFILE', None)
        start = time.monotonic()
        process = subprocess.Popen(
            ['/usr/bin/time', '-f', '%e %U %S %M', '-o', str(metrics), *command],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, start_new_session=True)
        try:
            output, errors = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            return {'exit': None, 'seconds': time.monotonic() - start}, b''
        result = {'exit': process.returncode, 'seconds': time.monotonic() - start}
        tokens = metrics.read_text().splitlines()[-1].split()
        result.update(user_seconds=float(tokens[1]), system_seconds=float(tokens[2]),
                      peak_rss_kib=int(tokens[3]))
        phases = collections.Counter()
        for line in errors.splitlines():
            try:
                item = json.loads(line)
                if item['phase'] in ('staging', 'privacy', 'projection', 'output'):
                    phases[item['phase']] += float(item['seconds'])
            except (ValueError, KeyError, TypeError):
                pass
        if phases:
            result['phases'] = dict(phases)
        return result, output


def check(item, binary, validator, out, references, timeout, validation_timeout):
    ident = item['id']
    source = Path(item['path'])
    destination = out/ident/'asr'
    before = digest(source)
    result = {key: item[key] for key in ('id', 'agent', 'bytes')}
    measurement, output = measured(
        [str(binary.resolve()), 'convert', '--agent', item['agent'], str(source),
         '--out', str(destination)], timeout, profile=True)
    result['measurement'] = measurement
    result['source_sha256'] = before
    result['source_unchanged'] = before == digest(source)
    if measurement['exit'] != 0:
        result['status'] = 'conversion_timeout' if measurement['exit'] is None else 'conversion_failed'
        # Remove only this run's unfinished staging data and outputs.
        import shutil
        shutil.rmtree(destination, ignore_errors=True)
        return result
    try:
        result['conversion'] = json.loads(output)
    except ValueError:
        result['status'] = 'conversion_summary_failed'
        return result
    result['comparison'] = compare(destination, references, ident)
    checked, output = measured(
        ['node', str(validator.resolve()), '--summary', '--json', str(destination)],
        validation_timeout)
    result['validation_measurement'] = checked
    if checked['exit'] is not None:
        try:
            validation = json.loads(output)
            result['validation'] = {key: validation[key] for key in
                                    ('valid', 'files', 'records', 'errors', 'warnings', 'inputFailures', 'counts')}
        except (ValueError, KeyError):
            result['status'] = 'validation_summary_failed'
            return result
    result['status'] = status(result, timeout)
    return result


def status(result, timeout):
    if not result['source_unchanged']:
        return 'source_changed'
    if result['validation_measurement']['exit'] is None:
        return 'validation_timeout'
    if result['validation_measurement']['exit'] != 0:
        return 'validation_failed'
    validation = result.get('validation', {})
    if (validation.get('valid') is not True or validation.get('errors') != 0 or
            validation.get('inputFailures') != 0):
        return 'validation_failed'
    if result['measurement']['seconds'] >= timeout:
        return 'performance_failed'
    if result['comparison'] != 'equal':
        return result['comparison']
    return 'passed'


def summary(results):
    groups = {}
    for agent in sorted({r['agent'] for r in results.values()}):
        rows = [r for r in results.values() if r['agent'] == agent]
        conversion = collections.Counter()
        validation = collections.Counter()
        for row in rows:
            conversion.update(row.get('conversion', {}).get('diagnostics', {}))
            validation.update(row.get('validation', {}).get('counts', {}))
        groups[agent] = {
            'files': len(rows), 'statuses': dict(collections.Counter(r['status'] for r in rows)),
            'seconds': percentiles([r['measurement']['seconds'] for r in rows]),
            'peak_rss_kib': percentiles([r['measurement']['peak_rss_kib'] for r in rows
                                         if 'peak_rss_kib' in r['measurement']]),
            'completed_memory_measurements': sum('peak_rss_kib' in r['measurement'] for r in rows),
            'records': sum(r.get('validation', {}).get('records', 0) for r in rows),
            'errors': sum(r.get('validation', {}).get('errors', 0) for r in rows),
            'warnings': sum(r.get('validation', {}).get('warnings', 0) for r in rows),
            'conversion_codes': dict(conversion), 'validation_codes': dict(validation),
        }
    return {'workers': 1, 'by_agent': groups}


def run(args):
    os.umask(0o077)
    args.out.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(args.out, 0o700)
    manifest = json.loads(args.catalog.read_text())
    catalog_path = args.out/'sample-catalog.json'
    if catalog_path.exists() and json.loads(catalog_path.read_text()) != manifest:
        raise ValueError('use a fresh output directory for a different catalog')
    write_json(catalog_path, manifest)
    result_path = args.out/'performance-counts.json'
    results = json.loads(result_path.read_text()) if result_path.exists() else {}
    for item in manifest['files']:
        ident = item['id']
        if args.recheck:
            result = results.get(ident)
            if (result is None or result['measurement']['exit'] != 0 or
                    'validation' not in result):
                continue
            result['comparison'] = compare(args.out/ident/'asr', args.reference, ident)
            result['status'] = status(result, args.timeout_seconds)
        elif ident in results:
            continue
        else:
            result = check(item, args.binary, args.validator, args.out, args.reference,
                           args.timeout_seconds, args.validation_timeout_seconds)
            results[ident] = result
        write_json(result_path, results)
        print(json.dumps({'file': ident, 'status': result['status'],
                          'seconds': round(result['measurement']['seconds'], 3),
                          'completed': len(results)}), flush=True)
    aggregate = summary(results)
    write_json(args.out/'performance-summary.json', aggregate)
    print(json.dumps(aggregate), flush=True)
    return int(len(results) != len(manifest['files']) or
               any(r['status'] != 'passed' for r in results.values()))
