#!/usr/bin/env python3
"""Assemble a local recorder and merge only its native hook registrations."""

import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile

AGENTS = ("claude-code", "cursor", "copilot-cli", "codebuddy", "qoder", "droid",
          "devin", "kiro", "junie", "lingma", "firebender", "antigravity", "auggie", "tabnine")
MODULES = ("shared.py", "adapters.py", "content.py", "observer.py", "projection.py", "storage.py", "tool_records.py", "file_changes.py")


def registrations(agent, config, script, output, full=False):
    hooks = {}
    for native in config["events"]:
        command = shlex.join(["env", "ASR_OUTPUT_DIR=" + str(output),
                              "ASR_CONTENT=" + ("full" if full else "metadata"),
                              sys.executable, "-I", "-S", str(script), native])
        handler = {"type": "command", "command": command,
                   "timeout": 1000 if agent in {"auggie", "tabnine"} else 1}
        if agent == "junie":
            # Synchronous PermissionRequest exit 0 would skip the user's
            # dialog. Async hooks are advisory and cannot decide permissions.
            handler["async"] = True
        if agent == "cursor":
            hooks[native] = [{"command": command, "timeout": 1, "failClosed": False}]
        elif agent == "copilot-cli":
            hooks[native] = [{"type": "command", "bash": command, "timeoutSec": 1}]
        elif agent == "firebender":
            hooks[native] = [handler]
        elif agent == "kiro":
            hooks[native] = [{"name": "ASR " + native, "trigger": native,
                              "action": {"type": "command", "command": command},
                              "timeout": 1, "enabled": True}]
        elif agent == "antigravity" and native not in {"PreToolUse", "PostToolUse"}:
            hooks[native] = [handler]
        else:
            if agent == "claude-code":
                handler["onFailure"] = "continue"
            hooks[native] = [{"hooks": [handler]}]
    return hooks


def owned(handler, script):
    if not isinstance(handler, dict):
        return False
    for key in ("command", "bash"):
        if isinstance(handler.get(key), str):
            try:
                if str(script) in shlex.split(handler[key]):
                    return True
            except ValueError:
                pass
    return False


def merge(document, hooks, script, unwrapped=False, uninstall=False):
    result = json.loads(json.dumps(document))
    target = result if unwrapped else result.setdefault("hooks", {})
    if not isinstance(target, dict):
        raise ValueError("hooks must be an object")
    for event, entries in list(target.items()):
        if not isinstance(entries, list):
            raise ValueError("hook event must be an array")
        kept = []
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("hooks"), list):
                handlers = [h for h in entry["hooks"] if not owned(h, script)]
                if handlers:
                    kept.append({**entry, "hooks": handlers})
            elif not owned(entry, script):
                kept.append(entry)
        if kept:
            target[event] = kept
        else:
            target.pop(event, None)
    if not uninstall:
        for event, entries in hooks.items():
            target.setdefault(event, []).extend(entries)
    if not unwrapped and not target:
        result.pop("hooks", None)
    return result


def merge_native(agent, document, hooks, script, path, uninstall=False):
    if agent == "kiro":
        if document.get("version", "v1") != "v1":
            raise ValueError("unsupported Kiro standalone hook version")
        entries = document.get("hooks", [])
        if not isinstance(entries, list):
            raise ValueError("Kiro standalone hooks must be an array")
        kept = [entry for entry in entries if not (isinstance(entry, dict)
                and owned(entry.get("action"), script))]
        if not uninstall:
            kept.extend(entry for group in hooks.values() for entry in group)
        return {**document, "version": "v1", "hooks": kept}
    if agent == "antigravity":
        result = json.loads(json.dumps(document))
        # Each top-level key is a native named hook group. Remove only our
        # commands, including in a group renamed by the user.
        for name, group in list(result.items()):
            if isinstance(group, dict):
                changed = False
                for event, entries in list(group.items()):
                    if not isinstance(entries, list) or not any(owned(e, script) or
                            (isinstance(e, dict) and isinstance(e.get("hooks"), list)
                             and any(owned(h, script) for h in e["hooks"])) for e in entries):
                        continue
                    changed = True
                    remaining = merge({event: entries}, {}, script, unwrapped=True, uninstall=True)
                    if event in remaining:
                        group[event] = remaining[event]
                    else:
                        group.pop(event)
                if changed and not group:
                    result.pop(name)
        if not uninstall:
            name = "asr-session-recorder"
            group = result.get(name, {})
            if not isinstance(group, dict):
                raise ValueError("recorder hook group must be an object")
            for event, entries in hooks.items():
                target = group.setdefault(event, [])
                if not isinstance(target, list):
                    raise ValueError("hook event must be an array")
                target.extend(entries)
            result[name] = group
        return result
    unwrapped = (agent == "droid" and path.name == "hooks.json"
                 or agent == "devin" and path.name == "hooks.v1.json")
    result = merge(document, hooks, script, unwrapped, uninstall)
    if agent in {"cursor", "copilot-cli", "firebender"} and not uninstall:
        if document.get("version", 1) != 1:
            raise ValueError("unsupported native hook configuration version")
        result["version"] = 1
    return result


def atomic_json(path, data):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("refusing a symlink configuration")
    fd, temp = tempfile.mkstemp(prefix=".asr-hooks-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=True)
            file.write("\n")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agent", choices=AGENTS)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--content", choices=("metadata", "full"), default="metadata")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args(argv)
    prefix = args.prefix.expanduser().resolve()
    script = prefix / args.agent / "record.py"
    if args.config is None and args.agent != "claude-code":
        parser.error("--config is required for this agent")
    if args.output_dir is None and not args.uninstall:
        parser.error("--output-dir is required for installation")
    root = Path(__file__).resolve().parent.parent
    config = json.loads((root / args.agent / "adapter.json").read_text())
    output = args.output_dir.expanduser().resolve() if args.output_dir else prefix / "captures"
    hooks = registrations(args.agent, config, script, output, args.content == "full")
    if args.config:
        path = args.config.expanduser().absolute()
        document = json.loads(path.read_text()) if path.exists() else {}
        result = merge_native(args.agent, document, hooks, script, path, args.uninstall)
    if not args.uninstall:
        (prefix / "hooks-core").mkdir(mode=0o700, parents=True, exist_ok=True)
        (prefix / args.agent).mkdir(mode=0o700, exist_ok=True)
        for module in MODULES:
            target = prefix / "hooks-core" / module
            if target.is_symlink():
                raise ValueError("refusing a symlink installation file")
            shutil.copyfile(root / "hooks-core" / module, target)
            target.chmod(0o600)
        helpers = root.parent / "python/agent_session_record/src/agent_session_record"
        target_helpers = prefix / "hooks-core/_shared/agent_session_record"
        target_helpers.mkdir(mode=0o700, parents=True, exist_ok=True)
        for name in ("__init__.py", "hooks.py", "privacy.py", "references.py", "content.py", "repository.py", "hook-conventions.json"):
            target = target_helpers / name
            if target.is_symlink():
                raise ValueError("refusing a symlink installation file")
            shutil.copyfile(helpers / name, target)
            target.chmod(0o600)
        for name in ("adapter.json", "record.py", "README.md"):
            target = prefix / args.agent / name
            if target.is_symlink():
                raise ValueError("refusing a symlink installation file")
            shutil.copyfile(root / args.agent / name, target)
            target.chmod(0o600)
        if args.agent == "claude-code":
            atomic_json(prefix / args.agent / ".claude-plugin/plugin.json", {
                "name": "asr-hooks", "version": "0.1.0", "license": "Apache-2.0",
                "author": {"name": "Agent Session Record contributors"},
                "description": "Passive Agent Session Record hook recorder."})
            atomic_json(prefix / args.agent / "hooks/hooks.json", {"hooks": hooks})
    if args.config:
        atomic_json(path, result)
    print("Recorder removed from configuration." if args.uninstall else "Recorder installed.")


if __name__ == "__main__":
    main()
