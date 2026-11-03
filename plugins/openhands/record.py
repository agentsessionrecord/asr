"""Silent fail-open command entry point."""
try:
    from asr_openhands import main
    main()
except Exception:
    pass
