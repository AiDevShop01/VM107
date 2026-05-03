"""
Phase 44 Wave 0 — Coordinator routing integration test scaffolds.

Tests Coordinator delegation routing and no-retry policy.
All tests are xfail(strict=False) until Plan 44-05 Task 1 implements the
Coordinator routing integration.

Test names MUST match 44-VALIDATION.md "Per-Task Verification Map" exactly.
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest


@pytest.mark.xfail(reason="Implementation pending in Plan 44-05", strict=False)
def test_routes_substantive():
    """
    Substantive user input causes Coordinator to dispatch to idea_agent.

    Asserts that is_substantive() → True for the input AND that
    call_subordinate is invoked with agent_id="idea_agent".

    Graduates in Plan 44-05 Task 1 when Coordinator routing integration is wired.
    """
    from core.agents.invocation import route_coordinator_input  # noqa: F401
    raise NotImplementedError("Coordinator integration not yet implemented — Plan 44-05 Task 1")


@pytest.mark.xfail(reason="Implementation pending in Plan 44-05", strict=False)
def test_no_coordinator_retry():
    """
    Subordinate failure does NOT trigger Coordinator retry.

    Asserts call_subordinate is called exactly once; exception propagates
    without Coordinator catching and retrying.

    Per CONTEXT.md: fail-fast — scheduler decides retry policy, not Coordinator.
    Graduates in Plan 44-05 Task 1.
    """
    from core.agents.invocation import route_coordinator_input  # noqa: F401
    raise NotImplementedError("Coordinator integration not yet implemented — Plan 44-05 Task 1")
