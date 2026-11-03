"""Canonical ASR-011 component encoding shared by Python producers."""
import unicodedata


def encode_component(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Expected a non-empty reference component")
    return "".join("".join(f"%{byte:02X}" for byte in char.encode("utf-8"))
                   if char in "%:# " or unicodedata.category(char) == "Cc" else char
                   for char in value)


def session_reference(agent: str, session: str, *, namespace: str | None = None,
                      record: str | None = None) -> str:
    components = [agent]
    if namespace is not None:
        components.append(encode_component(namespace))
    components.append(encode_component(session))
    return ":".join(components) + ("#" + encode_component(record) if record is not None else "")
