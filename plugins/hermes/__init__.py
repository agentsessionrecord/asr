"""Hermes directory plugin entry point."""
def register(plugin):
    try:
        from asr_hermes import register as install
        install(plugin)
    except Exception:
        pass
