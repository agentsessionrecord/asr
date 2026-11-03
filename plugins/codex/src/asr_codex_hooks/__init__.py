"""Codex command hook recorder. Importing this package performs no I/O."""

EVENTS = (
    "PreModelRequest", "PostModelRequest", "PreToolUse", "PermissionRequest",
    "PostToolUse", "PreCompact", "PostCompact", "SessionStart", "SessionEnd",
    "UserPromptSubmit", "SubagentStart", "SubagentStop", "Stop", "Interrupt",
)
