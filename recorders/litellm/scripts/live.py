#!/usr/bin/env python3
"""Run an isolated synthetic agent session.

All services are child processes stopped by PID. Only ASR files and a count-only
summary survive cleanup. Supply an existing compatible endpoint credential file.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from live_provider import loopback_endpoint, private_json

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('agent', choices=['claude-code', 'codex'])
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--prototype', type=Path, required=True, help='Read-only prototype tools/gateway-recorder directory')
    parser.add_argument('--model', required=True)
    parser.add_argument('--upstream-base-url', default=os.environ.get('ASR_PROVIDER_BASE_URL'))
    args = parser.parse_args()
    endpoint = loopback_endpoint(args.upstream_base_url)
    os.umask(0o077)
    args.evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    output = args.evidence.resolve() / (args.agent + '-' + time.strftime('%Y%m%dT%H%M%S', time.gmtime()))
    output.mkdir(mode=0o700)
    cache = Path.home() / '.cache'
    temporary = Path(tempfile.mkdtemp(prefix='asr-litellm-live-', dir=cache))
    scratch, home = temporary / 'repo', temporary / 'home'
    scratch.mkdir()
    home.mkdir()
    key = args.key_file.read_text().strip()
    env = {name: value for name, value in os.environ.items() if not name.startswith(('CLAUDE', 'ANTHROPIC_', 'CODEX_', 'OPENAI_'))}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / '.config'), XDG_CACHE_HOME=str(home / '.cache'),
               LITELLM_MASTER_KEY=key, ASR_UPSTREAM_AUTHORIZATION='Bearer ' + key,
               ASR_OUTPUT_DIR=str(output / 'asr'), LITELLM_LOCAL_MODEL_COST_MAP='True',
               DO_NOT_TRACK='1', LITELLM_TELEMETRY='False', DISABLE_OTEL='true')
    services = []
    summary = {'agent': args.agent, 'model': args.model}

    def git(*argv):
        return subprocess.check_output(['git', *argv], cwd=scratch, env=env, text=True, stderr=subprocess.DEVNULL).strip()

    def stop(process):
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    try:
        git('init', '--quiet')
        git('config', 'user.name', 'ASR Test')
        git('config', 'user.email', 'asr@example.invalid')
        git('config', 'commit.gpgsign', 'false')
        git('config', 'core.hooksPath', '/dev/null')
        (scratch / 'add.mjs').write_text('export const add = (a, b) => a - b;\n')
        (scratch / 'add.test.mjs').write_text("import { add } from './add.mjs';\nimport assert from 'node:assert/strict';\nassert.equal(add(2, 3), 5);\n")
        git('add', '.')
        git('commit', '--quiet', '-m', 'Add synthetic fixture')
        initial = git('rev-parse', 'HEAD')
        # Put the prototype downstream of LiteLLM to observe the same exchanges.
        ready, capture = temporary / 'ready.json', temporary / 'capture.jsonl'
        with (temporary / 'prototype.log').open('w') as log:
            prototype = subprocess.Popen(['node', str(args.prototype / 'bin/asr-gateway.js'), 'proxy', '--capture', str(capture), '--ready', str(ready)],
                                         env={**env, 'ASR_GATEWAY_UPSTREAM': endpoint}, stdout=log, stderr=log)
        services.append(prototype)
        deadline = time.monotonic() + 20
        while not ready.exists() and prototype.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        upstream_port = json.loads(ready.read_text())['port']
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        config = temporary / 'litellm.yaml'
        example = Path(__file__).resolve().parents[1] / 'config.example.yaml'
        config.write_text(example.read_text().replace('http://127.0.0.1:PORT', f'http://127.0.0.1:{upstream_port}'))
        with (temporary / 'litellm.log').open('w') as log:
            proxy = subprocess.Popen([str(Path(sys.executable).parent / 'litellm'), '--config', str(config), '--host', '127.0.0.1', '--port', str(port), '--num_workers', '1'],
                                     cwd=temporary, env=env, stdout=log, stderr=log)
        services.append(proxy)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if proxy.poll() is not None:
                raise RuntimeError('LITELLM_START_FAILED')
            try:
                with urlopen(f'http://127.0.0.1:{port}/health/liveliness', timeout=1) as response:
                    if response.status == 200:
                        break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError('LITELLM_START_TIMEOUT')
        task = ('Work only in this synthetic scratch Git repository. Do not access the network, credentials, other projects, or start subagents. '
                'Read add.mjs and add.test.mjs. Fix add(a,b) to return the sum. Run node --test add.test.mjs. '
                'Make one local Git commit with subject Fix addition. Do not push. Reply in one sentence.')
        if args.agent == 'claude-code':
            env.update(CLAUDE_CONFIG_DIR=str(home / 'claude'))
            settings = home / 'claude-provider.json'
            private_json(settings, {'env': {'ANTHROPIC_BASE_URL': f'http://127.0.0.1:{port}/asr/anthropic', 'ANTHROPIC_AUTH_TOKEN': key}})
            command = ['claude', '--settings', str(settings), '--print', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}', '--tools', 'Read,Edit,Bash',
                       '--allowedTools', 'Read,Edit,Bash(node *),Bash(git *)', '--permission-mode', 'dontAsk', '--session-id', str(uuid.uuid4()),
                       '--model', args.model, '--effort', 'low', '--max-budget-usd', '2', '--output-format', 'stream-json', '--verbose', task]
        else:
            (home / 'codex').mkdir()
            env.update(CODEX_HOME=str(home / 'codex'))
            settings = home / 'codex/config.toml'
            with settings.open('x') as stream:
                os.chmod(settings, 0o600)
                stream.write('model_provider = \"asr-gw\"\n[model_providers.asr-gw]\nname = \"ASR test gateway\"\nwire_api = \"responses\"\n'
                             + 'base_url = ' + json.dumps(f'http://127.0.0.1:{port}/asr/openai/v1') + '\n'
                             + 'http_headers = { Authorization = ' + json.dumps('Bearer ' + key) + ' }\n')
            prefix = 'model_providers.asr-gw.'
            command = ['codex', 'exec', '--json', '--color', 'never', '--sandbox', 'danger-full-access',
                       '-c', 'approval_policy="never"', '-c', 'model_provider="asr-gw"', '-c', prefix + 'name="ASR test gateway"',
                       '-c', prefix + 'base_url=' + json.dumps(f'http://127.0.0.1:{port}/asr/openai/v1'), '-c', prefix + 'wire_api="responses"',
                       '-c', prefix + 'supports_websockets=false', '-c', 'features.multi_agent=false',
                       '-c', 'model=' + json.dumps(args.model), '-c', 'model_reasoning_effort="low"', task]
        agent_env = {name: value for name, value in env.items()
                     if name not in ('LITELLM_MASTER_KEY', 'ASR_UPSTREAM_AUTHORIZATION')}
        with (temporary / 'agent.stdout').open('w') as out, (temporary / 'agent.stderr').open('w') as err:
            agent = subprocess.Popen(command, env=agent_env, cwd=scratch, stdout=out, stderr=err)
            try:
                agent.wait(timeout=300)
            finally:
                stop(agent)
        summary['agentExitCode'] = agent.returncode
        test = subprocess.run(['node', '--test', 'add.test.mjs'], cwd=scratch, env=env, capture_output=True)
        summary.update(testExitCode=test.returncode, committed=git('rev-parse', 'HEAD') != initial,
                       cleanWorktree=not bool(git('status', '--porcelain')))
        # Stop forwarding before building the prototype capture.
        for service in reversed(services):
            stop(service)
        prototype_output = temporary / 'prototype-asr'
        built = subprocess.run(['node', str(args.prototype / 'bin/asr-gateway.js'), 'build', '--capture', str(capture), '--out', str(prototype_output)], capture_output=True)
        summary['prototypeBuildExitCode'] = built.returncode
        from asr_litellm.protocol import META
        def records(path):
            return [json.loads(line) for line in path.read_text().splitlines()]
        actual = [r for p in (output / 'asr').glob('*.jsonl') for r in records(p)]
        expected = [r for p in prototype_output.glob('*.jsonl') for r in records(p)]
        def selected(items, kind):
            if kind == 'inference':
                return [(r.get('model'), r.get('usage')) for r in items if r['type'] == kind]
            keys = ('callId', 'name', 'input', 'inputText') if kind == 'tool_call' else ('callId', 'status', 'content')
            return [{k: r[k] for k in keys if k in r} for r in items if r['type'] == kind]
        summary['counts'] = {kind: sum(r['type'] == kind for r in actual) for kind in ('session', 'inference', 'message', 'tool_call', 'tool_result', 'gap')}
        summary['prototypeMatches'] = {kind: selected(actual, kind) == selected(expected, kind) for kind in ('inference', 'tool_call', 'tool_result')}
        summary['toolDefinitions'] = sum(len(r.get('tools', [])) for r in actual)
        summary['groupingKeys'] = [r['_meta'][META]['groupingKey'] for r in actual if r['type'] == 'session']
        validator = Path(__file__).resolve().parents[3] / 'tools/validator/bin/asr-validate.js'
        summary['validation'] = []
        for path in (output / 'asr').glob('*.jsonl'):
            checked = subprocess.run(['node', str(validator), '--json', str(path)], capture_output=True, text=True)
            try:
                result = json.loads(checked.stdout)
                # Keep only counts and diagnostic codes, never record text.
                summary['validation'].append({'exitCode': checked.returncode, 'result': result})
            except ValueError:
                summary['validation'].append({'exitCode': checked.returncode})
        summary['credentialFound'] = any(key.encode() in p.read_bytes() for p in output.rglob('*') if p.is_file())
        summary['success'] = bool(actual) and summary['agentExitCode'] == 0 and test.returncode == 0 and summary['committed'] and all(summary['prototypeMatches'].values()) and all(v['exitCode'] == 0 for v in summary['validation']) and not summary['credentialFound']
        if not summary['success']:
            for name in ('litellm.log', 'agent.stderr', 'agent.stdout'):
                path = temporary / name
                if path.exists():
                    (output / name).write_text(path.read_text(errors='replace').replace(key, '[REDACTED]'))
    except Exception as error:
        summary['failureCode'] = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        # Private diagnostics are transient and scrubbed of the known credential.
        for name in ('litellm.log', 'agent.stderr'):
            path = temporary / name
            if path.exists():
                text = path.read_text(errors='replace').replace(key, '[REDACTED]')
                (output / name).write_text(text)
    finally:
        for service in reversed(services):
            stop(service)
        summary['servicesStopped'] = all(p.poll() is not None for p in services)
        shutil.rmtree(temporary)
        summary['scratchRemoved'] = not temporary.exists()
        (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({'success': summary.get('success', False), 'failureCode': summary.get('failureCode'), 'evidence': str(output)}))
    return 0 if summary.get('success') else 1


if __name__ == '__main__':
    raise SystemExit(main())
