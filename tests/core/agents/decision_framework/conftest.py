"""Shared fixtures for Phase 47.3 framework tests.

These fixtures build EvaluationContext payloads in 6 canonical scenarios.
Imported by every per-evaluator and aggregator test.

NOTE: This file imports symbols not yet shipped (Plan 02/03/04). The fixtures
are defined defensively so pytest collection succeeds; tests using them xfail
naturally on the import error inside the fixture body.

Wave 0 — fixtures filled in by Plans 02/03/05.
"""
from __future__ import annotations
import pytest

# All fixtures attempt the import at use-time so pytest collection succeeds.

@pytest.fixture
def ctx_all_pass():
    """Every Tier-2 envelope returns ok with strong-signal data; no overrides."""
    from core.agents.decision_framework.context import EvaluationContext  # xfail on import
    # Construct a context where every category will return pass.
    # Implementer fills in real envelope shapes when Plan 02 ships them.
    raise NotImplementedError("Plan 02 will fill in canonical happy-path fixture")


@pytest.fixture
def ctx_partial_context():
    """News + Macro = not_available; primitives + liquidity = ok.
    Should drive partial_context=True and 2 HIGH-tier confidence adjustments.
    """
    from core.agents.decision_framework.context import EvaluationContext  # xfail on import
    raise NotImplementedError("Plan 02 will fill in partial-context fixture")


@pytest.fixture
def ctx_hard_reject_fired():
    """Momentum=fail (no displacement) → hard_reject 'no displacement' fires.
    Score should still be computed; recommendation forced to 'avoid'.
    """
    from core.agents.decision_framework.context import EvaluationContext  # xfail on import
    raise NotImplementedError("Plan 05 will fill in hard-reject fixture")


@pytest.fixture
def ctx_override_applied():
    """Model 2 Option 1 Short with strong momentum → Location weight 0.5x."""
    from core.agents.decision_framework.context import EvaluationContext  # xfail on import
    raise NotImplementedError("Plan 05 will fill in override fixture")


@pytest.fixture
def ctx_all_not_available():
    """Every Tier-2 + Tier-3 returns not_available.
    Score=0, confidence reduced to floor, partial_context=True.
    """
    from core.agents.decision_framework.context import EvaluationContext  # xfail on import
    raise NotImplementedError("Plan 02 will fill in worst-case fixture")


@pytest.fixture
def ctx_mixed():
    """Mix of pass/fail/unclear/not_available across the 9 categories.
    Used for aggregator tests."""
    from core.agents.decision_framework.context import EvaluationContext  # xfail on import
    raise NotImplementedError("Plan 02 will fill in mixed fixture")
