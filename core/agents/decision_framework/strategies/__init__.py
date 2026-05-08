"""Strategy override modules. Each module's import side-effect registers its
overrides + hard-reject predicates with the framework.

Plan 05 ships ``model_2_option_1_short.py`` here. Until then this package is
intentionally empty so ``Framework()`` boot still works in test environments
that don't need strategy-specific behavior (the boot-time hard-reject
assertion fires only against strategy YAMLs that ship with predicates).
"""
# Plan 05 will add: from . import model_2_option_1_short  # noqa: F401
