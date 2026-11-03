"""Private provider settings with endpoint checks before any model request."""

import json
import os
from pathlib import Path
import stat
import tomllib
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from live_provider import loopback_endpoint

PROVIDER = "asr_e2e_local"


class CheckFailure(Exception):
    """A public diagnostic code, never source text or credentials."""


def require(condition, code):
    if not condition:
        raise CheckFailure(code)


def private_file(path, text):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        stream.write(text)


def provision(directory, credential, anthropic_base, openai_base, anthropic_model, openai_model):
    anthropic_base = loopback_endpoint(anthropic_base)
    openai_base = loopback_endpoint(openai_base)
    require(bool(anthropic_model) and bool(openai_model), "provider_models_required")
    require(bool(credential) and "\n" not in credential and "\r" not in credential,
            "invalid_proxy_credential")
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    private_file(directory / "claude.json", json.dumps({
        "env": {"ANTHROPIC_BASE_URL": anthropic_base, "ANTHROPIC_AUTH_TOKEN": credential},
        "autoMemoryEnabled": False, "model": anthropic_model,
    }))
    # The token belongs to this named provider. No default cloud auth file exists.
    private_file(directory / "codex.toml", f'''model = {json.dumps(openai_model)}
model_provider = "{PROVIDER}"
model_reasoning_effort = "low"
approval_policy = "never"
sandbox_mode = "danger-full-access"
[features]
hooks = true
multi_agent = false
[model_providers.{PROVIDER}]
name = "ASR synthetic test endpoint"
base_url = {json.dumps(openai_base)}
wire_api = "responses"
http_headers = {{ Authorization = {json.dumps("Bearer " + credential)} }}
''')
    private_file(directory / "pi.json", json.dumps({"providers": {PROVIDER: {
        "baseUrl": openai_base, "api": "openai-responses", "apiKey": credential,
        "models": [{"id": openai_model, "name": "ASR local test model",
                    "reasoning": True, "input": ["text"],
                    "contextWindow": 128000, "maxTokens": 4096}],
    }}}))
    return verify(directory)


def verify(directory):
    directory = Path(directory)
    for name in ("claude.json", "codex.toml", "pi.json"):
        file = directory / name
        require(not file.is_symlink() and stat.S_IMODE(file.stat().st_mode) == 0o600,
                "provider_file_permissions")
    claude = json.loads((directory / "claude.json").read_text())
    codex = tomllib.loads((directory / "codex.toml").read_text())
    pi = json.loads((directory / "pi.json").read_text())
    loopback_endpoint(claude["env"]["ANTHROPIC_BASE_URL"])
    require(codex["model_provider"] == PROVIDER, "codex_provider_not_local")
    require(set(codex["model_providers"]) == {PROVIDER}, "codex_extra_provider")
    loopback_endpoint(codex["model_providers"][PROVIDER]["base_url"])
    require(set(pi["providers"]) == {PROVIDER}, "pi_provider_not_local")
    loopback_endpoint(pi["providers"][PROVIDER]["baseUrl"])
    require(pi["providers"][PROVIDER]["baseUrl"] == codex["model_providers"][PROVIDER]["base_url"], "provider_endpoint_mismatch")
    require(pi["providers"][PROVIDER]["models"][0]["id"] == codex["model"], "provider_model_mismatch")
    credential = claude["env"]["ANTHROPIC_AUTH_TOKEN"]
    require(bool(credential) and codex["model_providers"][PROVIDER]["http_headers"] == {
        "Authorization": "Bearer " + credential}, "codex_credential_mismatch")
    require(pi["providers"][PROVIDER]["apiKey"] == credential, "pi_credential_mismatch")
    return credential
