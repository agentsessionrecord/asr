"""Remove recognizable secrets from selected output fields."""

import re

SECRET_KEY = re.compile(r"(?:password|secret|authorization|cookie|(?:api|access|auth|refresh|session)[_-]?(?:key|token))", re.I)
SECRET_TEXT = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{20,}|(?:AKIA|ASIA)[A-Z0-9]{16}|"
    r"eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,})\b"
    r"|\bBearer\s+[^\s\"']+"
    r"|-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----.*?-----END (?:[A-Z0-9]+ )?PRIVATE KEY-----"
    r"|(?i:password|api[_-]?key|access[_-]?token|secret)\s*[:=]\s*[^\s\"']+",
    re.S,
)
URL_USERINFO = re.compile(r"(https?://)[^\s/@]+@", re.I)


def scrub(value):
    if isinstance(value, dict):
        if value.get("type") == "reasoning":
            if value.get("visibility") in ("encrypted", "omitted"):
                return {key: value[key] for key in ("type", "visibility", "author", "origin") if key in value}
            value = {key: value[key] for key in ("type", "text", "summary", "visibility", "author", "origin") if key in value}
        return {key: "[redacted]" if SECRET_KEY.fullmatch(key) else scrub(item) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, str):
        return URL_USERINFO.sub(r"\1", SECRET_TEXT.sub("[redacted]", value))
    return value
