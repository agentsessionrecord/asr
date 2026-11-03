"""Silent fail-open command entry point."""
try:
    from asr_mistral_vibe import main
    main()
except Exception:
    pass
