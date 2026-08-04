"""Phase 85.1 — Backfill end-to-end: backfill_indicator_descriptions.py fix.

Requirement mapping:
    PHASE85.1-REQ-2: backfill_indicator_descriptions.py runs end-to-end against
    10-anchor fixture without AttributeError: module 'agent' has no attribute 'run_agent'.
    upsert_description called 10× (one per indicator in --limit 10 run).

The existing phase85 test (test_indicator_description_backfill.py) uses a
broken mock-based approach that doesn't catch the AttributeError regression.
This test replaces it with a correct end-to-end approach that:
    1. Mocks _dispatch_agent_sync at the correct import path (not agent.run_agent).
    2. Mocks upsert_description to count calls.
    3. Runs the backfill CLI directly via importlib or subprocess.
    4. Asserts no AttributeError and upsert_description called exactly --limit times.

All tests are xfail until Plan 04 fixes the backfill callsite and wires it to
_dispatch_agent_sync instead of the broken agent.run_agent reference.
"""

from __future__ import annotations

import pytest


@pytest.mark.xfail(
    reason="Plan 04 — backfill _dispatch_agent_sync fix not yet implemented",
    strict=False,
)
def test_backfill_loops_over_indicators_without_attributeerror(
    monkeypatch,
    mock_dispatch_agent_sync,
):
    """backfill_indicator_descriptions runs --limit 10 without AttributeError.

    The Phase 85 backfill script calls agent.run_agent() which does not exist.
    Plan 04 replaces this callsite with _dispatch_agent_sync (the same path
    used by the live task dispatcher).

    Test approach:
        1. Patch VM107.backfill.backfill_indicator_descriptions._dispatch_agent_sync
           to mock_dispatch_agent_sync (already provides a working return value).
        2. Patch VM107.persistence.economic_indicator_description.upsert_description
           to a counting mock.
        3. Import + call the backfill main() with limit=10.
        4. Assert no AttributeError was raised.
        5. Assert upsert_description called exactly 10 times.

    If the backfill still references agent.run_agent, this test catches it as
    an ImportError / AttributeError (which xfail-strict=False allows during Wave 0).
    """
    from unittest.mock import MagicMock, patch

    # Default routing (BACKFILL_USE_AGENT_ZERO unset -> "0") goes through
    # _dispatch_describer_direct since Phase 86-10; force the agent-sync path
    # so the patched _dispatch_agent_sync is actually the callsite under test.
    monkeypatch.setenv("BACKFILL_USE_AGENT_ZERO", "1")

    mock_upsert = MagicMock()

    try:
        with (
            patch(
                "backfill.backfill_indicator_descriptions._dispatch_agent_sync",
                mock_dispatch_agent_sync,
            ),
            patch(
                "persistence.economic_indicator_description.upsert_description",
                mock_upsert,
            ),
        ):
            from backfill import backfill_indicator_descriptions  # noqa: F401

            backfill_indicator_descriptions.main(limit=10)

    except AttributeError as exc:
        if "run_agent" in str(exc):
            pytest.fail(
                f"AttributeError: module 'agent' has no attribute 'run_agent' — "
                f"Plan 04 must fix the backfill callsite. Original error: {exc}"
            )
        raise

    assert mock_upsert.call_count == 10, (
        f"upsert_description must be called exactly 10 times (limit=10), "
        f"got {mock_upsert.call_count}"
    )


@pytest.mark.xfail(
    reason="Plan 04 — backfill --skip-manual-override flag not yet implemented",
    strict=False,
)
def test_backfill_skips_manual_override_rows(
    monkeypatch,
    mock_dispatch_agent_sync,
    mock_brain_state_collection,
):
    """Backfill must skip indicators whose ai_description has is_manual_override=True.

    Some indicators have hand-curated descriptions that must not be overwritten
    by the LLM backfill.  The backfill script should filter these out before
    dispatching agent calls.

    Test approach:
        1. Patch indicator fetch to return 10 indicators, 3 with is_manual_override=True.
        2. Run backfill with limit=10.
        3. Assert _dispatch_agent_sync called 7 times (10 - 3 skipped).
        4. Assert upsert_description called 7 times.
    """
    from unittest.mock import MagicMock, call, patch

    # Force the agent-sync routing path (default -> _dispatch_describer_direct
    # since Phase 86-10) so the patched _dispatch_agent_sync is exercised.
    monkeypatch.setenv("BACKFILL_USE_AGENT_ZERO", "1")

    mock_upsert = MagicMock()

    # 10 indicators: 3 manual overrides, 7 eligible for LLM backfill
    indicators = []
    for i in range(10):
        indicators.append({
            "indicator_id": f"IND{i:03d}",
            "ai_description": f"Description {i}",
            "is_manual_override": i < 3,  # First 3 are manual overrides
        })

    mock_fetch = MagicMock(return_value=indicators)

    try:
        with (
            patch(
                "backfill.backfill_indicator_descriptions.fetch_indicators_for_backfill",
                mock_fetch,
            ),
            patch(
                "backfill.backfill_indicator_descriptions._dispatch_agent_sync",
                mock_dispatch_agent_sync,
            ),
            patch(
                "persistence.economic_indicator_description.upsert_description",
                mock_upsert,
            ),
        ):
            from backfill import backfill_indicator_descriptions  # noqa: F401

            backfill_indicator_descriptions.main(limit=10)

    except AttributeError as exc:
        if "run_agent" in str(exc):
            pytest.fail(f"AttributeError from broken agent.run_agent callsite: {exc}")
        raise

    assert mock_dispatch_agent_sync.call_count == 7, (
        f"Expected 7 agent dispatches (10 total - 3 manual overrides), "
        f"got {mock_dispatch_agent_sync.call_count}"
    )
    assert mock_upsert.call_count == 7, (
        f"Expected 7 upsert_description calls, got {mock_upsert.call_count}"
    )
