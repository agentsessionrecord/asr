"""Transparent JSONL stdio proxy with private, append-only ASR output."""
from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys

from agent_session_record.safety import read_bounded
from .recorder import Recorder, MAX_FRAME


class UnavailableRecorder:
    disabled = True

    def close(self):
        pass


def decode(data):
    def pairs(items):
        result = {}
        for name, value in items:
            if name in result:
                raise ValueError('Duplicate key')
            result[name] = value
        return result
    value = json.loads(data, object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Non-finite number')))
    if not isinstance(value, dict):
        raise ValueError('Expected object')
    return value


async def proxy(recorder, command):
    process = await asyncio.create_subprocess_exec(*command, stdin=asyncio.subprocess.PIPE,
                                                   stdout=asyncio.subprocess.PIPE, limit=MAX_FRAME)
    reader = asyncio.StreamReader(limit=MAX_FRAME)
    transport, _ = await asyncio.get_running_loop().connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)

    async def relay(source, target, direction):
        pending = bytearray()
        oversized = False
        while data := await source.read(64 * 1024):
            # Forward first. Storage failures and oversized frames cannot change
            # the bytes seen by either side of the ACP connection.
            if direction == 'client':
                target.write(data)
                await target.drain()
            else:
                target.write(data)
                target.flush()
            if recorder.disabled:
                continue
            for piece in data.splitlines(keepends=True):
                # Only LF frames JSONL. Other control characters stay in data.
                # splitlines also recognizes CR, so accumulate it until LF.
                if not oversized:
                    if len(pending) + len(piece) > MAX_FRAME:
                        pending.clear()
                        oversized = True
                    else:
                        pending.extend(piece)
                if not piece.endswith(b'\n'):
                    continue
                try:
                    value = decode(pending) if not oversized else None
                except (ValueError, UnicodeError, RecursionError):
                    value = None
                try:
                    if value is None:
                        recorder.malformed()
                    else:
                        recorder.observe(direction, value)
                except Exception:
                    recorder.disable()
                pending.clear()
                oversized = False
        if pending or oversized:
            recorder.malformed()
        if direction == 'client':
            target.close()

    loop = asyncio.get_running_loop()
    owner = asyncio.current_task()
    loop.add_signal_handler(signal.SIGTERM, owner.cancel)
    incoming = asyncio.create_task(relay(reader, process.stdin, 'client'))
    outgoing = asyncio.create_task(relay(process.stdout, sys.stdout.buffer, 'agent'))
    try:
        done, _ = await asyncio.wait([incoming, outgoing], return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        if outgoing not in done:
            await outgoing
        return await process.wait()
    finally:
        loop.remove_signal_handler(signal.SIGTERM)
        transport.close()
        for task in (incoming, outgoing):
            if not task.done():
                task.cancel()
        await asyncio.gather(incoming, outgoing, return_exceptions=True)
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 5)
            except TimeoutError:
                process.kill()
                await process.wait()
        try:
            recorder.close()
        except Exception:
            print('ASR_ACP_CAPTURE_FAILED', file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--agent', required=True, help='Registered short name or maintainer-controlled reverse-DNS name')
    parser.add_argument('--secret-file', action='append', default=[], help='Private file containing one known secret, excluded from capture')
    parser.add_argument('--selector', action='append', default=[], metavar='ID=mode|approval')
    parser.add_argument('--traffic', help='Replay local synthetic direction/message JSONL instead of starting an agent')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not args.traffic and not command:
        parser.error('Provide an agent command after --')
    try:
        secrets = [read_bounded(path, 1024 * 1024).decode('utf-8').strip() for path in args.secret_file]
        selectors = dict(item.split('=', 1) for item in args.selector)
        recorder = Recorder(args.output, args.agent, secrets=secrets, selectors=selectors)
    except (OSError, ValueError, KeyError, TypeError):
        print('ASR_ACP_CAPTURE_FAILED', file=sys.stderr)
        if args.traffic:
            raise SystemExit(1) from None
        recorder = UnavailableRecorder()
    try:
        if args.traffic:
            with open(args.traffic, 'rb') as stream:
                for data in iter(lambda: stream.readline(MAX_FRAME + 1), b''):
                    if len(data) > MAX_FRAME:
                        raise ValueError('Native frame exceeds byte limit')
                    value = decode(data)
                    recorder.observe(value['direction'], value['message'])
            recorder.close()
            return
        raise SystemExit(asyncio.run(proxy(recorder, command)))
    except asyncio.CancelledError:
        print('ASR_ACP_STOPPED', file=sys.stderr)
        raise SystemExit(143) from None
    except (OSError, ValueError, KeyError, TypeError):
        # Error codes never print source content, environment values or credentials.
        print('ASR_ACP_CAPTURE_FAILED', file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
