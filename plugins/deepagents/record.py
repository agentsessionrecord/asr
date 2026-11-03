"""Silent fail-open command entry point."""
try:
    from asr_deepagents import main
    main()
except Exception:
    pass
