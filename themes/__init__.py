"""Phase 94 Wave 3a — Theme Engine package.

Houses the curated theme catalog (themes/catalog/*.yaml), test suite,
and the MacroThemeEngine entrypoint. The state machine and evidence
accumulation primitives live under :mod:`core.theme_engine` so the
Wave-0 RED scaffold (``core.theme_engine.state_machine`` import) flips
to GREEN here.

Per CONTEXT.md §H.2/H.3 the theme engine is DETERMINISTIC — no LLM on
the strength path. Specialist analyst agents (94-05) explain themes in
natural language; they never recompute the strength.
"""
