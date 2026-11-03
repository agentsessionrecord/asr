import json
from pathlib import Path
import pytest

from agent_session_record import encode_component, session_reference
from agent_session_record.privacy import credential_key, environment_secrets, redact_text


def test_reference_encodes_only_required_characters():
    native = "run/one@two+three: #%\n\x7f\x85é"
    assert encode_component(native) == "run/one@two+three%3A%20%23%25%0A%7F%C2%85é"
    assert session_reference("hermes", native, namespace="a:b", record="r #1") == (
        "hermes:a%3Ab:" + encode_component(native) + "#r%20%231")
    with pytest.raises(ValueError):
        encode_component("")


@pytest.mark.parametrize("key", ["max_tokens", "inputTokens", "tokens_used", "token_usage", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL"])
def test_ordinary_names_are_not_credentials(key):
    assert not credential_key(key)


@pytest.mark.parametrize("key", ["api_key", "apiKey", "x-api-key", "accessToken", "refresh_token", "Authorization", "password", "cookie", "private_key", "AWS_SECRET_ACCESS_KEY"])
def test_credential_names(key):
    assert credential_key(key)


def test_environment_and_known_patterns(monkeypatch):
    monkeypatch.setenv("GIT_AUTHOR_NAME", "synthetic-public-author")
    monkeypatch.setenv("SYNTHETIC_API_KEY", "synthetic-private-key-value")
    assert "synthetic-public-author" not in environment_secrets()
    assert "synthetic-private-key-value" in environment_secrets()
    forms = json.loads((Path(__file__).parent / "fixtures/credentials.json").read_text())
    for form in forms:
        value = form.get("prefix", "".join(form.get("prefixParts", []))) + form["repeat"] * form["count"] + form.get("suffix", "".join(form.get("suffixParts", [])))
        assert value not in redact_text("before " + value + " after")


@pytest.mark.parametrize("name", ["api_key", "apiKey", "password", "session_token", "token", "client_secret"])
def test_credentials_in_serialized_json_and_quoted_assignments(name):
    value = "synthetic-private value"
    for text in (json.dumps({name: value}), f"{name}='{value}'", f'{name}="{value}"'):
        assert value not in redact_text(text)


def test_url_and_basic_credentials():
    value = "synthetic-private-value"
    for text in (f"https://{value}@example.invalid/repo", f"https://user:{value}@example.invalid/repo",
                 f"https://example.invalid/path?token={value}&other=public"):
        assert value not in redact_text(text)
    import base64
    encoded = base64.b64encode(b'synthetic-user:synthetic-password').decode()
    assert encoded not in redact_text('Basic ' + encoded)
    assert redact_text('Follow basic instructions.') == 'Follow basic instructions.'
    assert credential_key("token") and credential_key("cookies")
    assert redact_text('max_tokens=42 inputTokens=10 tokens_used=3') == 'max_tokens=42 inputTokens=10 tokens_used=3'
