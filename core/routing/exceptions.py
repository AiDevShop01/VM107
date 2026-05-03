"""Phase 43.2 router exception hierarchy.

RouterChainExhaustedError is raised by execute_with_fallback when all models in the
[primary] + fallback chain fail with retryable errors. Carries the full attempt trace
preserving exception OBJECTS (not strings) so callers can do:

    try:
        result = await execute_with_fallback(...)
    except RouterChainExhaustedError as e:
        for attempt in e.attempts:
            if isinstance(attempt["error"], RateLimitError):
                # provider_instability signal — Phase 44+ Brain integration
                ...
"""

from __future__ import annotations


class RouterChainExhaustedError(Exception):
    """Raised when all models in [primary] + fallback chain fail with retryable errors.

    Attributes:
        attempts: list of dicts shaped {"model": str, "error": Exception, "chain_index": int}.
                  Exception OBJECTS preserved (NOT stringified) so callers retain isinstance semantics.
                  Order matches execution order (first attempt first).
    """

    def __init__(self, attempts: list[dict]):
        self.attempts = attempts
        super().__init__(
            f"Router fallback chain exhausted after {len(attempts)} attempt(s): "
            + ", ".join(f"{a['model']}->{type(a['error']).__name__}" for a in attempts)
        )
