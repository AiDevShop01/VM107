#!/usr/bin/env python3
"""Phase 43.2 — pre-commit hook: forbid direct LiteLLM/parse calls outside allowlist.

ALLOWLIST (paths that may legitimately use forbidden patterns):
  - core/routing/                              (failover wrapper code)
  - core/agents/structured_output.py           (the safe_parse module itself)
  - core/routing/failover_executor.py          (the failover wrapper itself)
  - core/contracts/                            (legitimate Pydantic validation callers)
  - extensions/python/                         (CONTEXT.md: extension that owns the wrapper —
                                                e.g. extensions/python/.../fallback_executor.py;
                                                in practice extensions reference .unified_call as
                                                attribute access, not direct call, so no false
                                                positives — but spec compliance requires this prefix)
  - tests/                                     (test files mock these patterns)
  - models.py                                  (LiteLLMChatWrapper.unified_call IS the wrapper)
  - scripts/check_forbidden_patterns.py        (script itself contains pattern strings)

FORBIDDEN PATTERNS:
  - \\.parse_raw\\(                            (Pydantic v1 deprecated)
  - \\.parse_obj\\(                            (Pydantic v1 deprecated)
  - \\.model_validate_json\\(                  (must go through safe_parse)
  - \\.model_validate\\(                       (must go through safe_parse — outside allowlist)
  - litellm\\.completion\\(                    (must go through router)
  - \\.unified_call\\(                         (must go through execute_with_fallback)
  - \\.with_structured_output\\(               (must go through bind_structured)

IMPLEMENTATION DEFERRED TO PLAN 03 — this skeleton only validates the hook wires up.
"""

from __future__ import annotations

import sys


def main(argv: list[str]) -> int:
    # Plan 03 implements the actual scan + allowlist logic.
    # For Wave 0: skeleton always passes so commits don't break before Plan 03 ships.
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
