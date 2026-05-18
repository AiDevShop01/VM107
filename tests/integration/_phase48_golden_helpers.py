"""Shared helpers for the 9 Phase 48 E2E golden integration tests.

Centralizes the verbose machinery of:
  - Constructing canonical typed stubs (Hypothesis / StrategySpec /
    CodeModule / BuildReport / BacktestResult / CriticVerdict).
  - Wiring the 6 typed wrappers (run_strategy / run_code / run_build /
    run_backtest / run_critic) via monkeypatch.
  - Patching the orchestrator's _get_db, freeze_snapshot_hash, and emit
    helpers so the loop runs end-to-end against mongomock without a live
    CapabilityRegistry.

Each golden file imports from this module + asserts the terminal
RefinementOutcome.termination_reason matches the expected enum + the right
sequence of emit_event calls happened (loop_started / iteration_started /
... / loop_terminated).
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from core.contracts.schemas import (
    BacktestMetrics,
    BacktestResult,
    BuildReport,
    CanonicalIssueId,
    CodeModule,
    CriticVerdict,
    Hypothesis,
    RefinementTarget,
    StrategyFamily,
    StrategySpec,
)


# ---------------------------------------------------------------------------
# Canonical typed stubs — every golden composes these unless overriding.
# ---------------------------------------------------------------------------


def make_hypothesis(hyp_id: str = "hyp_phase48_test_001") -> Hypothesis:
    """Build a valid Hypothesis (with source_envelope_id None)."""
    return Hypothesis(
        hypothesis="Volatility breakouts on session-open ranges yield positive expectancy.",
        variables=["asset_class", "session"],
        confidence=0.7,
        source_envelope_id=None,
        schema_version=1,
    )


def make_strategy_spec(
    name: str = "spec_phase48",
    family: StrategyFamily = StrategyFamily.BREAKOUT,
    version: str = "0.0.1",
) -> StrategySpec:
    """Build a valid StrategySpec carrying the locked FieldMutability metadata."""
    return StrategySpec(
        name=name,
        features=["atr14", "rsi14"],
        rules=["enter on close > prior_high"],
        timeframes=["1h"],
        version=version,
        strategy_family=family,
        schema_version=1,
    )


def make_code_module(version: str = "0.0.1") -> CodeModule:
    return CodeModule(
        module_type="strategy",
        target_vm="vm101",
        contract="def signal(bar): ...",
        code="def signal(bar): return 0",
        tests="def test_signal(): assert True",
        version=version,
    )


def make_build_report(status: str = "success") -> BuildReport:
    return BuildReport(
        status=status,  # type: ignore[arg-type]
        artifact_id="art_test",
        errors=[],
        warnings=[],
        schema_version=1,
    )


def make_backtest_result(
    *,
    sample_size: int = 250,
    win_rate: float = 0.55,
    max_drawdown: float = 0.10,
    profit_factor: float = 1.5,
    consecutive_losses: int = 3,
    regime_coverage: float = 0.5,
    rr: float = 1.5,
    confidence: float = 0.6,
) -> BacktestResult:
    """Default kwargs PASS all 4 acceptance floors + all 4 hard vetoes."""
    return BacktestResult(
        metrics=BacktestMetrics(
            win_rate=win_rate,
            rr=rr,
            max_drawdown=max_drawdown,
            profit_factor=profit_factor,
            consecutive_losses=consecutive_losses,
            regime_coverage=regime_coverage,
        ),
        sample_size=sample_size,
        confidence=confidence,
    )


def make_refinement_target(
    *,
    canonical_issue_id: CanonicalIssueId = CanonicalIssueId.SAMPLE_SIZE_TOO_SMALL,
    scope: str = "CODE_MODULE",
    target_field: str | None = None,
    issue_type: str = "small_sample",
    severity: str = "MEDIUM",
    source_critic_verdict_id: str = "cv_seed",
) -> RefinementTarget:
    """Build a valid RefinementTarget. target_field defaults are scope-aware:
    CODE_MODULE → 'code' (CodeModule-only); STRATEGY_SPEC → 'features'."""
    if target_field is None:
        target_field = "code" if scope == "CODE_MODULE" else "features"
    return RefinementTarget(
        scope=scope,  # type: ignore[arg-type]
        canonical_issue_id=canonical_issue_id,
        target_field=target_field,
        issue=f"{issue_type} on {target_field}",
        issue_type=issue_type,
        severity=severity,  # type: ignore[arg-type]
        suggested_change=f"tune {target_field}",
        source_critic_verdict_id=source_critic_verdict_id,
        schema_version=1,
    )


def make_critic_verdict(
    *,
    verdict: str = "ACCEPT",
    confidence: float = 0.85,
    refinement_targets: list[RefinementTarget] | None = None,
    failure_modes: list[str] | None = None,
    loaded_skills: list[str] | None = None,
    snapshot_hash: str = "phase48-test-snapshot-deadbeef",
) -> CriticVerdict:
    return CriticVerdict(
        verdict=verdict,  # type: ignore[arg-type]
        confidence=confidence,
        refinement_targets=refinement_targets or [],
        failure_modes=failure_modes or [],
        rationale="test rationale",
        loaded_skills=loaded_skills or ["breakout-critic"],
        source_critic_verdict_id=None,
        registry_snapshot_hash=snapshot_hash,
        schema_version=1,
    )


# ---------------------------------------------------------------------------
# Orchestrator wiring helper.
# ---------------------------------------------------------------------------


def seed_valid_hypothesis(db: Any, hypothesis_id: str) -> None:
    """Replace the Plan-00 stub Hypothesis doc with one carrying valid schema.

    Plan 00's `valid_hypothesis_id` fixture inserts a minimal placeholder
    (title + core_idea fields) that does NOT satisfy the real Hypothesis
    schema (hypothesis + variables + confidence). The goldens re-write the
    doc here so the orchestrator's _load_hypothesis call succeeds.
    """
    db["hypotheses"].replace_one(
        {"_id": hypothesis_id},
        {
            "_id": hypothesis_id,
            "hypothesis": "Volatility breakouts on session-open ranges yield positive expectancy.",
            "variables": ["asset_class", "session"],
            "confidence": 0.7,
            "source_envelope_id": None,
            "schema_version": 1,
        },
        upsert=True,
    )


def wire_orchestrator_for_golden(
    monkeypatch,
    *,
    db: Any,
    snapshot_hash: str,
    run_strategy_returns: list[StrategySpec],
    run_code_returns: list[CodeModule],
    run_build_returns: list[BuildReport],
    run_backtest_returns: list[BacktestResult],
    run_critic_returns: list[Any],  # accepts CriticVerdict OR side_effect exception
    seen_events: list[dict[str, Any]] | None = None,
    hypothesis_id: str = "hyp_phase48_test_001",
):
    """Patch the orchestrator's external surfaces with deterministic stubs.

    Returns a dict of mocks so callers can assert call counts / payloads.
    """
    if seen_events is None:
        seen_events = []

    # 0) Seed valid Hypothesis doc (overrides Plan-00 stub placeholder).
    seed_valid_hypothesis(db, hypothesis_id)

    # 1) Patch the DB resolver.
    monkeypatch.setattr(
        "core.agents.refinement_orchestrator.main_loop._get_db",
        lambda: db,
    )

    # 2) Patch snapshot_freeze.CapabilityRegistry.get().snapshot_hash so the
    #    iter-0 freeze writes our deterministic hash without a live registry.
    fake_registry = MagicMock()
    fake_registry.snapshot_hash = snapshot_hash
    monkeypatch.setattr(
        "core.agents.refinement_orchestrator.snapshot_freeze.CapabilityRegistry.get",
        lambda: fake_registry,
    )
    # state.initialize_loop_state also calls CapabilityRegistry.get().snapshot_hash.
    monkeypatch.setattr(
        "core.agents.refinement_orchestrator.state.CapabilityRegistry.get",
        lambda: fake_registry,
    )

    # 3) Patch all 5 typed wrappers in the main_loop's import surface.
    strat_mock = MagicMock(name="run_strategy", side_effect=list(run_strategy_returns))
    code_mock = MagicMock(name="run_code", side_effect=list(run_code_returns))
    build_mock = MagicMock(name="run_build", side_effect=list(run_build_returns))
    bt_mock = MagicMock(name="run_backtest", side_effect=list(run_backtest_returns))
    critic_mock = MagicMock(name="run_critic", side_effect=list(run_critic_returns))

    monkeypatch.setattr(
        "core.agents.refinement_orchestrator.main_loop.run_strategy", strat_mock
    )
    monkeypatch.setattr(
        "core.agents.refinement_orchestrator.main_loop.run_code", code_mock
    )
    monkeypatch.setattr(
        "core.agents.refinement_orchestrator.main_loop.run_build", build_mock
    )
    monkeypatch.setattr(
        "core.agents.refinement_orchestrator.main_loop.run_backtest", bt_mock
    )
    monkeypatch.setattr(
        "core.agents.refinement_orchestrator.main_loop.run_critic", critic_mock
    )
    # Routing module also imports run_strategy / run_code at module level.
    monkeypatch.setattr(
        "core.agents.refinement_orchestrator.refinement_routing.run_strategy",
        strat_mock,
    )
    monkeypatch.setattr(
        "core.agents.refinement_orchestrator.refinement_routing.run_code",
        code_mock,
    )

    # 4) Patch the Phase 56 emit endpoint so we don't hit a real HTTP server.
    def fake_emit(*, event_type, category, correlation_id, payload, causality_scope="IDEA"):
        seen_events.append(
            {
                "event_type": event_type,
                "category": category,
                "correlation_id": correlation_id,
                "payload": payload,
                "causality_scope": causality_scope,
            }
        )

    monkeypatch.setattr(
        "core.events.refinement_events.emit_event", fake_emit
    )
    monkeypatch.setattr(
        "core.agents.refinement_orchestrator.persistence.emit_event", fake_emit
    )
    monkeypatch.setattr(
        "core.events.phase56_client.emit_event", fake_emit
    )

    # 5) Patch the registry strategy YAML emitter so we don't write to the
    #    real registry/strategy/ dir during tests. acceptance_path imports
    #    emit_strategy_yaml; bypass with a no-op that returns the would-be
    #    path.
    def fake_emit_yaml(accepted_doc, output_dir=None):
        from pathlib import Path
        return Path(f"/tmp/test-registry/strategy/{accepted_doc['accepted_strategy_id']}.yaml")

    monkeypatch.setattr(
        "core.agents.refinement_orchestrator.acceptance_path.emit_strategy_yaml",
        fake_emit_yaml,
    )

    return {
        "run_strategy": strat_mock,
        "run_code": code_mock,
        "run_build": build_mock,
        "run_backtest": bt_mock,
        "run_critic": critic_mock,
        "seen_events": seen_events,
    }


def event_types_emitted(seen_events: list[dict[str, Any]]) -> list[str]:
    """Extract the ordered list of event_type values emitted during the loop."""
    return [e["event_type"] for e in seen_events]
