#!/usr/bin/env python3
"""Run an isolated OpenCode ACP smoke test and print counts only."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from live_provider import loopback_endpoint

async def run(args):
    with tempfile.TemporaryDirectory(prefix='asr-acp-live-') as directory:
        root = Path(directory)
        root.chmod(0o700)
        config_dir, workspace, output = root / 'config', root / 'work', root / 'asr'
        for path in (config_dir, workspace, output):
            path.mkdir(mode=0o700)
        endpoint = loopback_endpoint(args.base_url)
        config = {'autoupdate': False, 'model': 'local/' + args.model,
                  'provider': {'local': {'name': 'Local', 'npm': '@ai-sdk/openai-compatible',
                    'options': {'baseURL': endpoint, 'apiKey': Path(args.key_file).read_text().strip()},
                    'models': {args.model: {'name': 'Local model', 'limit': {'context': 100000, 'output': 1024},
                              'tool_call': False}}}},
                  'permission': {'*': 'deny'}}
        settings = config_dir / 'opencode.json'
        fd = os.open(settings, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(config, stream)
        configured = json.loads(settings.read_text())['provider']['local']['options']
        assert loopback_endpoint(configured['baseURL']) == endpoint
        assert configured['apiKey']
        (root / 'models.json').write_text('{}')
        env = {k: v for k, v in os.environ.items() if k in ('PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'HOME')}
        env.update(OPENCODE_TEST_HOME=str(root), OPENCODE_CONFIG_DIR=str(config_dir),
                   OPENCODE_CONFIG=str(settings), OPENCODE_DISABLE_AUTOUPDATE='true',
                   OPENCODE_DISABLE_MODELS_FETCH='true', OPENCODE_DISABLE_FILEWATCHER='true',
                   OPENCODE_MODELS_PATH=str(root / 'models.json'), OPENCODE_DB=str(root / 'opencode.db'),
                   XDG_CONFIG_HOME=str(root / 'xdg-config'), XDG_CACHE_HOME=str(root / 'cache'),
                   XDG_DATA_HOME=str(root / 'data'), XDG_STATE_HOME=str(root / 'state'))
        check = await asyncio.create_subprocess_exec(str(Path(args.agent_bin).resolve()), 'debug', 'config',
                    cwd=workspace, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        resolved_bytes, _ = await asyncio.wait_for(check.communicate(), 30)
        if check.returncode:
            raise RuntimeError('ACP_CONFIG_RESOLUTION_FAILED')
        resolved = json.loads(resolved_bytes)
        active = resolved.get('provider', {}).get('local', {}).get('options', {})
        if active.get('baseURL') != endpoint or not active.get('apiKey'):
            raise RuntimeError('ACP_RESOLVED_ENDPOINT_MISMATCH')
        # Keep all agent diagnostics private and remove them with the runtime.
        diagnostics = (root / 'diagnostics').open('wb')
        process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'asr_acp.cli', '--output', str(output),
                    '--agent', 'opencode', '--secret-file', str(args.key_file), '--', str(Path(args.agent_bin).resolve()), 'acp',
                    cwd=workspace, env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=diagnostics)
        notifications = permissions = 0
        async def request(ident, method, params):
            nonlocal notifications, permissions
            process.stdin.write((json.dumps({'jsonrpc': '2.0', 'id': ident, 'method': method, 'params': params}) + '\n').encode())
            await process.stdin.drain()
            while True:
                line = await asyncio.wait_for(process.stdout.readline(), 120)
                if not line:
                    raise RuntimeError('ACP_EOF')
                value = json.loads(line)
                if value.get('method') == 'session/request_permission':
                    permissions += 1
                    process.stdin.write((json.dumps({'jsonrpc': '2.0', 'id': value['id'], 'result': {'outcome': {'outcome': 'cancelled'}}}) + '\n').encode())
                    await process.stdin.drain()
                elif 'method' in value:
                    notifications += 1
                elif value.get('id') == ident:
                    if 'error' in value:
                        raise RuntimeError('ACP_RPC_ERROR:' + method + ':' + str(value['error'].get('code')))
                    return value['result']
        try:
            initialized = await request(1, 'initialize', {'protocolVersion': 1, 'clientCapabilities': {}, 'clientInfo': {'name': 'asr-scripted-client', 'version': '0.1'}})
            created = await request(2, 'session/new', {'cwd': str(workspace), 'mcpServers': []})
            # The agent must have loaded our private provider and selected its model before any model request.
            model = created.get('models', {}).get('currentModelId', '')
            for option in created.get('configOptions', []):
                if option.get('id') == 'model':
                    model = option.get('currentValue')
            if model != 'local/' + args.model:
                raise RuntimeError('ACP_PROVIDER_NOT_SELECTED')
            await request(3, 'session/prompt', {'sessionId': created['sessionId'], 'prompt': [{'type': 'text', 'text': 'Reply with the single word ready. Do not use tools or delegate.'}]})
            process.stdin.close()
            await asyncio.wait_for(process.wait(), 20)
            paths = list(output.glob('*.jsonl'))
            counts = Counter()
            errors = warnings = 0
            for path in paths:
                for line in path.read_text().splitlines():
                    counts[json.loads(line)['type']] += 1
                validation = await asyncio.create_subprocess_exec('node', str(Path(__file__).resolve().parents[3] / 'tools/validator/bin/asr-validate.js'), '--json', str(path), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                stdout, _ = await validation.communicate()
                result = json.loads(stdout)
                errors += result['errors'] if isinstance(result.get('errors'), int) else len(result.get('errors', []))
                warnings += result['warnings'] if isinstance(result.get('warnings'), int) else len(result.get('warnings', []))
                if validation.returncode:
                    raise RuntimeError('ASR_VALIDATION_FAILED')
            if not paths or not counts['message']:
                raise RuntimeError('ACP_EMPTY_CAPTURE')
            print(json.dumps({'agentVersion': initialized.get('agentInfo', initialized.get('info', {})).get('version'),
                              'sessions': len(paths), 'records': dict(counts), 'notifications': notifications,
                              'permissionRequests': permissions, 'validationErrors': errors, 'validationWarnings': warnings}))
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 5)
                except TimeoutError:
                    process.kill()
                    await process.wait()
            diagnostics.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent-bin', required=True)
    parser.add_argument('--key-file', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--base-url', default=os.environ.get('ASR_OPENAI_BASE_URL'))
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except (RuntimeError, TimeoutError, ValueError, OSError) as error:
        print(str(error) if isinstance(error, RuntimeError) else type(error).__name__, file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
