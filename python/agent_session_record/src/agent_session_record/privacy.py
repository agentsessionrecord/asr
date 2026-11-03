"""Credential names and known credential forms, without token-count matches."""
import os
import re
import json

TOKEN = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{12,}|sess-[A-Za-z0-9_-]{20,}|"
    r"gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|"
    r"xox[baprs]-[A-Za-z0-9-]{16,}|(?:AKIA|ASIA)[A-Z0-9]{16}|"
    r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b|"
    r"(?i:Bearer\s+)[A-Za-z0-9._~+/=-]+|(?i:Basic\s+)[A-Za-z0-9+/]{16,}={0,2}|"
    r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?(?:-----END [^-]*PRIVATE KEY-----|$)|"
    r"(?i:\b(?:password|passwd|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|"
    r"auth[_ -]?token|session[_ -]?token|authorization|client[_ -]?secret|secret|cookie|token)"
    r"[\"']?\s*[:=]\s*)(?:\"(?:\\.|[^\"\\\r\n])*\"|'(?:\\.|[^'\\\r\n])*'|[^\s,;}\"']+)|"
    r"(?<=://)[^/\s@]+@|"
    r"(?i:[?&](?:api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|"
    r"session[_-]?token|client[_-]?secret|password|secret|token)=)[^&#\s\"']*"
)
_NAMES = re.compile(
    r"(?:^|_)(?:api_key|access_token|refresh_token|auth_token|session_token|"
    r"authorization|password|passwd|secret|secrets|credential|credentials|"
    r"cookies|cookie|set_cookie|private_key|client_secret|secret_access_key)$|^token$", re.I)
_ENV = re.compile(r"(?:^|_)(?:KEY|TOKEN|PASSWORD|PASSWD|SECRET|CREDENTIALS?)(?:_|$)", re.I)
OPAQUE = {"signature", "encrypted_content", "encryptedContent"}


def credential_key(value: str) -> bool:
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    name = re.sub(r"[-. ]", "_", name)
    return bool(_NAMES.search(name))


def environment_secrets() -> tuple[str, ...]:
    return tuple(sorted({value for name, value in os.environ.items()
                         if (credential_key(name) or _ENV.search(name)) and len(value) >= 8},
                        key=len, reverse=True))


def credential_values(value) -> tuple[str, ...]:
    """Learn named credentials before filtering sibling text and metadata."""
    values = set()
    nodes = size = 0
    def walk(item, depth=0):
        nonlocal nodes, size
        nodes += 1
        if nodes > 100_000 or depth > 40:
            raise ValueError('credential_scan_capacity')
        if isinstance(item, dict):
            for key, child in item.items():
                if (isinstance(key, str) and credential_key(key) and isinstance(child, str) and child
                        and child.lower() not in ('[redacted]', '[omitted]')):
                    if child not in values:
                        size += len(child)
                        if size > 1024 * 1024:
                            raise ValueError('credential_scan_capacity')
                        values.add(child)
                elif key not in OPAQUE:
                    walk(child, depth + 1)
        elif isinstance(item, (list, tuple)):
            for child in item:
                walk(child, depth + 1)
        elif isinstance(item, str) and item.lstrip().startswith(('{', '[')):
            try:
                decoded = json.loads(item)
            except (ValueError, RecursionError):
                return
            walk(decoded, depth + 1)
    walk(value)
    return tuple(sorted(values, key=len, reverse=True))


def redact_text(value: str, secrets=(), replacement="[REDACTED]") -> str:
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            value = value.replace(secret, replacement)
    return TOKEN.sub(replacement, value)
