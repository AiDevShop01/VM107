"""
Phase 44 Wave 0 — Envelope persistence integration test scaffolds.

Tests that AgentEnvelope documents are written to MongoDB agent_envelopes
collection. All tests are xfail(strict=False) until Plan 44-03 Task 2
implements the persistence layer in the typed wrappers.

Test names MUST match 44-VALIDATION.md "Per-Task Verification Map" exactly.
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest


@pytest.mark.xfail(reason="Implementation pending in Plan 44-03", strict=False)
def test_envelope_written_success():
    """
    Successful run_strategy invocation writes one AgentEnvelope row with status=success.

    Asserts:
    - Exactly one document inserted to agent_envelopes
    - doc["status"] == "success"
    - doc["agent_id"] == "strategy_agent"
    - doc["envelope_id"] is a non-empty string

    Graduates in Plan 44-03 Task 2 when persistence layer is implemented.
    """
    from core.agents.invocation import run_strategy, write_envelope  # noqa: F401
    raise NotImplementedError("Persistence layer not yet implemented — Plan 44-03 Task 2")


@pytest.mark.xfail(reason="Implementation pending in Plan 44-03", strict=False)
def test_envelope_written_failure():
    """
    Failed agent invocation writes AgentEnvelope with status=failure.

    Asserts:
    - One document inserted with status=failure
    - error information is present in output field

    Graduates in Plan 44-03 Task 2.
    """
    from core.agents.invocation import run_strategy, write_envelope  # noqa: F401
    raise NotImplementedError("Persistence layer not yet implemented — Plan 44-03 Task 2")


@pytest.mark.xfail(reason="Implementation pending in Plan 44-03", strict=False)
def test_chain_provenance():
    """
    Idea Agent envelope_id appears as Strategy Agent envelope's source_envelope_id.

    The full provenance chain Idea → Strategy is verifiable via the
    source_envelope_id field.

    Graduates in Plan 44-03 Task 2.
    """
    from core.agents.invocation import run_idea, run_strategy  # noqa: F401
    raise NotImplementedError("Persistence layer not yet implemented — Plan 44-03 Task 2")
