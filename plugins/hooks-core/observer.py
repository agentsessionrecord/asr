#!/usr/bin/env python3
"""Silent, bounded, passive command-hook entry point for POSIX hosts."""

import os
import signal
import sys
import logging


def main(agent, event_name=None):
    # Cursor permission hooks reject empty/invalid JSON on exit 0. Exit 1 with
    # failClosed:false is its documented no-decision fail-open path.
    code = 1 if agent == "cursor" and event_name in {
        "preToolUse", "subagentStart", "beforeSubmitPrompt"
    } else 0
    def expired(*_):
        raise TimeoutError("Capture deadline")

    def lost():
        base = os.environ.get("ASR_OUTPUT_DIR")
        if base and os.path.isabs(base):
            from storage import open_file
            folder = os.path.join(base, agent)
            os.makedirs(folder, mode=0o700, exist_ok=True)
            root = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                fd = open_file(root, "capture.lost", os.O_CREAT | os.O_WRONLY)
                os.close(fd)
            finally:
                os.close(root)

    try:
        signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, 0.15)
        from adapters import load, normalize
        from projection import identifier
        from storage import capture, checked, decode

        config = load(agent)
        raw = sys.stdin.buffer.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            lost()
            return code
        event = normalize(decode(raw), config, event_name)
        if event is None:
            return code
        parent = identifier(event.get("session_id"))
        if parent is None:
            return code
        base = os.environ.get("ASR_OUTPUT_DIR")
        if not base or not os.path.isabs(base):
            return code
        os.makedirs(base, mode=0o700, exist_ok=True)
        root = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            checked(root, directory=True)
        finally:
            os.close(root)
        child = identifier(event.get("agent_id")) if config.get("child_ids") else None
        capture(os.path.join(base, agent), child or parent, event, parent, config)
    except BaseException:
        signal.setitimer(signal.ITIMER_REAL, 0)
        try:
            lost()
        except Exception:
            pass
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    return code
