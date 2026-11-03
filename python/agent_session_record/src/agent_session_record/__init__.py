"""ASR 0.1 generated models and an append-only writer."""
from .references import encode_component, session_reference

__all__ = ["Writer", "derive_id", "encode_component", "session_reference"]


def __getattr__(name):
    # Lightweight helpers also run in isolated, standard-library-only hooks.
    if name in {"Writer", "derive_id"}:
        from . import writer
        return getattr(writer, name)
    raise AttributeError(name)
