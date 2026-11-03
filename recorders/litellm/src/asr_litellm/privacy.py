"""Scrub credentials before an observation enters recorder state."""
from __future__ import annotations

import json
import re
from urllib.parse import quote

from agent_session_record.privacy import TOKEN, OPAQUE, credential_key, redact_text, environment_secrets

HEADER_ALLOWLIST = {"user-agent", "request-id", "x-request-id", "anthropic-version", "content-type",
                    "thread-id", "thread_id", "session-id", "session_id", "conversation_id",
                    "x-claude-code-agent-id", "x-claude-code-session-id", "originator", "x-codex-turn-metadata"}


def looks_like_token(value):
    return bool(TOKEN.search(str(value)))


class Scrubber:
    def __init__(self, *headers, secrets=()):
        values = set(filter(None, secrets)) | set(environment_secrets())
        for group in headers:
            for name, value in group.items():
                value = str(value)
                if credential_key(name) or looks_like_token(value):
                    values.update((value, re.sub(r'^(Bearer|Basic)\s+', '', value, flags=re.I)))
                    if 'cookie' in name.lower():
                        values.update(pair.partition('=')[2].strip() for pair in value.split(';'))
        self.secrets = values - {''}
        self.redacted = False

    def learn(self, value):
        if isinstance(value, dict):
            for key, child in value.items():
                if credential_key(key) and isinstance(child, str) and child:
                    self.secrets.add(child)
                elif key not in OPAQUE:
                    self.learn(child)
        elif isinstance(value, list):
            for item in value:
                self.learn(item)
        elif isinstance(value, str) and value[:1] in ('{', '['):
            try:
                self.learn(json.loads(value))
            except (ValueError, RecursionError):
                pass

    def text(self, value):
        output = value
        variants = {v for s in self.secrets for v in (s, json.dumps(s)[1:-1], quote(s, safe=''))}
        for secret in sorted(variants, key=len, reverse=True):
            output = output.replace(secret, '[REDACTED]')
        output = redact_text(output)
        output = re.sub(r'([?&](?:api[-_]?key|access_token|token|secret|password)=)[^&#\s"]*', r'\1[REDACTED]', output, flags=re.I)
        self.redacted |= output != value
        return output

    def clean(self, value):
        self.learn(value)
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.clean(item) for item in value]
        if isinstance(value, dict):
            # Opaque reasoning state is excluded by ASR-015, independently of redaction.
            result = {self.text(key): self.clean(child) for key, child in value.items() if key not in OPAQUE}
            if value.get('encrypted_content'):
                result['encrypted_content'] = True
            return result
        return value

    def headers(self, values):
        return {name.lower(): str(value) for name, value in values.items()
                if name.lower() in HEADER_ALLOWLIST and len(str(value)) <= 16384 and not credential_key(name) and not looks_like_token(value)
                and self.text(str(value)) == str(value)}
