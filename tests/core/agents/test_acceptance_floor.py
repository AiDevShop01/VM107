"""Phase 48 Plan 48-04 Task 4.2 — acceptance_floor deterministic classifier.

Implements REQ-48-D8. CONTEXT § Decision 8 — "Below floor -> Python forces
REFINE or REJECT BEFORE Critic LLM executes."

Severity policy (planner-locked, ACCEPT_FLOOR_BREACH_THRESHOLD=0.20):
- All 4 floors pass -> CRITIC_ELIGIBLE
- Any floor breached by >20% -> HARD_REJECT
- Any floor breached by <=20% (and no >20% breach) -> REFINABLE_WEAKNESS
- Mixed -> HARD_REJECT (worst-case wins)

Pure function: classify_acceptance(backtest_result) -> DeterministicAcceptanceResult.
No Mongo, no LLM, no Phase 56 client. Inputs in, decision out.
"""
from __future__ import annotations

import pytest

from core.contracts.schemas import (
    AcceptanceClassification,
    BacktestMetrics,
    BacktestResult,
    DeterministicAcceptanceResult,
)


def _br(
    *,
    sample_size: int = 250,
    win_rate: float = 0.55,
    max_drawdown: float = 0.10,
    profit_factor: float = 1.6,
    rr: float = 1.5,
    confidence: float = 0.6,
) -> BacktestResult:
    """Helper: build a BacktestResult with named overrides over a passing baseline."""
    return BacktestResult(
        metrics=BacktestMetrics(
            win_rate=win_rate,
            rr=rr,
            max_drawdown=max_drawdown,
            profit_factor=profit_factor,
        ),
        sample_size=sample_size,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# All-pass path.
# ---------------------------------------------------------------------------


def test_all_floors_pass_yields_critic_eligible():
    from core.agents.refinement_orchestrator.acceptance_floor import classify_acceptance

    result = classify_acceptance(_br())

    assert isinstance(result, DeterministicAcceptanceResult)
    assert result.classification == AcceptanceClassification.CRITIC_ELIGIBLE
    assert result.passed is True
    assert result.failed_constraints == []


# ---------------------------------------------------------------------------
# Severity policy: >20% breach -> HARD_REJECT; <=20% -> REFINABLE_WEAKNESS.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs,expected_classification,expected_breached",
    [
        # sample_size 10 / 200 -> breach = (200-10)/200 = 0.95 (95%) -> HARD_REJECT
        ({"sample_size": 10}, AcceptanceClassification.HARD_REJECT, {"sample_size"}),
        # sample_size 180 / 200 -> breach = (200-180)/200 = 0.10 (10%) -> REFINABLE
        ({"sample_size": 180}, AcceptanceClassification.REFINABLE_WEAKNESS, {"sample_size"}),
        # win_rate 0.40 / 0.45 -> breach = (0.45-0.40)/0.45 = 0.111 (~11%) -> REFINABLE
        ({"win_rate": 0.40}, AcceptanceClassification.REFINABLE_WEAKNESS, {"win_rate"}),
        # win_rate 0.30 / 0.45 -> breach = (0.45-0.30)/0.45 = 0.333 (~33%) -> HARD_REJECT
        ({"win_rate": 0.30}, AcceptanceClassification.HARD_REJECT, {"win_rate"}),
        # max_drawdown 0.25 over 0.20 ceiling -> breach = (0.25-0.20)/0.20 = 0.25 (25%) -> HARD_REJECT
        ({"max_drawdown": 0.25}, AcceptanceClassification.HARD_REJECT, {"max_drawdown"}),
        # max_drawdown 0.22 over 0.20 -> breach = (0.22-0.20)/0.20 = 0.10 (10%) -> REFINABLE
        ({"max_drawdown": 0.22}, AcceptanceClassification.REFINABLE_WEAKNESS, {"max_drawdown"}),
        # profit_factor 1.0 / 1.2 -> breach = (1.2-1.0)/1.2 = 0.167 (~17%) -> REFINABLE
        ({"profit_factor": 1.0}, AcceptanceClassification.REFINABLE_WEAKNESS, {"profit_factor"}),
        # profit_factor 0.5 / 1.2 -> breach = (1.2-0.5)/1.2 = 0.583 (~58%) -> HARD_REJECT
        ({"profit_factor": 0.5}, AcceptanceClassification.HARD_REJECT, {"profit_factor"}),
    ],
)
def test_severity_policy_classifies_each_single_metric_breach(
    kwargs, expected_classification, expected_breached
):
    from core.agents.refinement_orchestrator.acceptance_floor import classify_acceptance

    result = classify_acceptance(_br(**kwargs))

    assert result.classification == expected_classification
    assert set(result.failed_constraints) == expected_breached
    assert result.passed is (expected_classification == AcceptanceClassification.CRITIC_ELIGIBLE)


# ---------------------------------------------------------------------------
# Mixed: HARD breach + MILD breach -> HARD_REJECT (worst-case wins).
# failed_constraints lists EVERY breached metric (even mild).
# ---------------------------------------------------------------------------


def test_mixed_hard_plus_mild_breach_classifies_as_hard_reject():
    from core.agents.refinement_orchestrator.acceptance_floor import classify_acceptance

    # sample_size=10 (95% breach -> HARD) + win_rate=0.40 (11% breach -> MILD).
    result = classify_acceptance(_br(sample_size=10, win_rate=0.40))

    assert result.classification == AcceptanceClassification.HARD_REJECT
    assert result.passed is False
    # BOTH breached metrics are reported, not just the hard one.
    assert set(result.failed_constraints) == {"sample_size", "win_rate"}


# ---------------------------------------------------------------------------
# metrics_snapshot completeness.
# ---------------------------------------------------------------------------


def test_metrics_snapshot_contains_all_four_metrics_and_derived_breach_pct():
    from core.agents.refinement_orchestrator.acceptance_floor import classify_acceptance

    result = classify_acceptance(
        _br(sample_size=180, win_rate=0.40, max_drawdown=0.22, profit_factor=1.0)
    )

    snap = result.metrics_snapshot
    # Raw metrics for all 4 floors.
    assert snap["sample_size"] == 180
    assert snap["win_rate"] == 0.40
    assert snap["max_drawdown"] == 0.22
    assert snap["profit_factor"] == 1.0
    # Per-metric breach percentages (the derived audit substrate).
    assert "derived_breach_pct_per_metric" in snap
    bp = snap["derived_breach_pct_per_metric"]
    assert pytest.approx(bp["sample_size"], rel=1e-6) == 0.10
    assert pytest.approx(bp["win_rate"], rel=1e-6) == (0.45 - 0.40) / 0.45
    assert pytest.approx(bp["max_drawdown"], rel=1e-6) == (0.22 - 0.20) / 0.20
    assert pytest.approx(bp["profit_factor"], rel=1e-6) == (1.2 - 1.0) / 1.2


# ---------------------------------------------------------------------------
# Same classification, different failed_constraints lists.
# ---------------------------------------------------------------------------


def test_two_distinct_snapshots_can_share_classification_but_differ_in_failed_constraints():
    from core.agents.refinement_orchestrator.acceptance_floor import classify_acceptance

    r1 = classify_acceptance(_br(win_rate=0.40))            # REFINABLE on win_rate
    r2 = classify_acceptance(_br(max_drawdown=0.22))        # REFINABLE on max_drawdown

    assert r1.classification == AcceptanceClassification.REFINABLE_WEAKNESS
    assert r2.classification == AcceptanceClassification.REFINABLE_WEAKNESS
    assert set(r1.failed_constraints) != set(r2.failed_constraints)
    assert "win_rate" in r1.failed_constraints
    assert "max_drawdown" in r2.failed_constraints


# ---------------------------------------------------------------------------
# Purity: no I/O, no module-level mutable state, no LLM, no Mongo, no registry.
# ---------------------------------------------------------------------------


def test_classify_acceptance_is_pure_no_mongo_no_llm_no_registry():
    """AST guard: scan acceptance_floor.py for forbidden imports / calls."""
    import ast
    import pathlib

    src = pathlib.Path(
        "/Volumes/ HardDrive/FinGPT/VM107/core/agents/refinement_orchestrator/acceptance_floor.py"
    ).read_text()
    tree = ast.parse(src)

    forbidden_modules = {
        "pymongo",
        "mongomock",
        "httpx",
        "requests",
        "core.events.phase56_client",
        "core.events",
        "core.registry.capability_registry",
        "core.agents.invocation",
    }
    forbidden_attr_chains = {"db", "collection", "emit_event", "CapabilityRegistry"}

    bad_imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in forbidden_modules:
                    bad_imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module in forbidden_modules:
                bad_imports.append(node.module)

    assert not bad_imports, (
        f"acceptance_floor.py must be pure; forbidden imports found: {bad_imports}"
    )

    # No top-level "open" / "requests.post" / "httpx.post" call literally.
    src_text = src
    for forbidden_attr in forbidden_attr_chains:
        # Function calls. ".db." would suggest a Mongo handle; "CapabilityRegistry" name use.
        # Conservative grep — acceptance_floor.py is small (~50 LOC).
        if forbidden_attr in ("emit_event", "CapabilityRegistry"):
            assert forbidden_attr not in src_text, (
                f"acceptance_floor.py must not reference {forbidden_attr!r}"
            )


def test_classify_acceptance_does_not_persist_or_mutate_inputs():
    """Same BacktestResult passed twice -> same DeterministicAcceptanceResult (frozen inputs)."""
    from core.agents.refinement_orchestrator.acceptance_floor import classify_acceptance

    br = _br(sample_size=180)
    r1 = classify_acceptance(br)
    r2 = classify_acceptance(br)

    assert r1.classification == r2.classification
    assert r1.failed_constraints == r2.failed_constraints
    # BacktestResult is BaseContract frozen — the input itself can't be mutated;
    # this confirms classify_acceptance doesn't try (no exception, same outputs).
    assert r1 == r2


# ---------------------------------------------------------------------------
# Schema typing: returns DeterministicAcceptanceResult schema_version=1.
# ---------------------------------------------------------------------------


def test_classify_acceptance_returns_versioned_schema():
    from core.agents.refinement_orchestrator.acceptance_floor import classify_acceptance

    result = classify_acceptance(_br())

    assert isinstance(result, DeterministicAcceptanceResult)
    assert result.schema_version == 1
