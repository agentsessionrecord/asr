"""Silent recording, hook configuration, and optional command-hook observation."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
from threading import Thread

from . import EVENTS


def capture(data, output, full, outcome=None):
    from .recorder import now, record

    def expired(*_):
        raise TimeoutError("Capture deadline")

    old_handler = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, 0.75)
    try:
        record(data, output, full=full, receipt=now(), outcome=outcome)
    except Exception:
        signal.setitimer(signal.ITIMER_REAL, 0)
        from asr_plugin_core.storage import mark_loss
        mark_loss(output)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("record", "config", "wrap"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--full", action="store_true", help="Record available content after secret exclusion")
    args, command = parser.parse_known_args()
    if args.action == "config":
        invocation = [sys.executable, "-m", "asr_codex_hooks", "record", "--output", str(args.output.resolve())]
        if args.full:
            invocation.append("--full")
        handler = {"type": "command", "command": shlex.join(invocation), "timeout": 1}
        print(json.dumps({"hooks": {event: [{"hooks": [handler]}] for event in EVENTS}}, indent=2))
        return 0
    if args.action == "record":
        # Read is also bounded. A broken hook sender must not stall the agent.
        from .recorder import MAX_INPUT
        def expired(*_):
            raise TimeoutError("Input deadline")
        signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, 0.1)
        try:
            data = sys.stdin.buffer.read(MAX_INPUT + 1)
        except Exception:
            signal.setitimer(signal.ITIMER_REAL, 0)
            from asr_plugin_core.storage import mark_loss
            mark_loss(args.output)
            return 0
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        capture(data, args.output, args.full)
        return 0
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("wrap requires -- followed by an existing command and arguments")
    # The configured command is trusted configuration. Never execute stdin fields.
    # Forward each stream as it arrives. Retain only a bounded observation copy.
    from .recorder import MAX_INPUT
    data = sys.stdin.buffer.read(MAX_INPUT + 1)
    with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as child:
        observed = {}

        def forward(name, source, target):
            retained = bytearray()
            omitted = False
            while chunk := source.read1(65536):
                try:
                    target.write(chunk)
                    target.flush()
                except BrokenPipeError:
                    pass
                if len(retained) + len(chunk) <= MAX_INPUT // 2 and not omitted:
                    retained.extend(chunk)
                else:
                    omitted = True
            try:
                observed[name] = None if omitted else retained.decode("utf-8")
            except UnicodeDecodeError:
                observed[name] = None

        threads = [Thread(target=forward, args=("stdout", child.stdout, sys.stdout.buffer)),
                   Thread(target=forward, args=("stderr", child.stderr, sys.stderr.buffer))]
        for thread in threads:
            thread.start()
        try:
            child.stdin.write(data)
            while chunk := sys.stdin.buffer.read(65536):
                child.stdin.write(chunk)
            child.stdin.close()
        except BrokenPipeError:
            pass
        child.wait()
        for thread in threads:
            thread.join()
    response = {"exitCode": child.returncode, **{key: value for key, value in observed.items() if value is not None}}
    if None in observed.values():
        response["outputOmitted"] = True
    capture(data, args.output, args.full, response)
    if child.returncode < 0:
        if -child.returncode not in (signal.SIGKILL, signal.SIGSTOP):
            signal.signal(-child.returncode, signal.SIG_DFL)
        os.kill(os.getpid(), -child.returncode)
    return child.returncode


if __name__ == "__main__":
    raise SystemExit(main())
