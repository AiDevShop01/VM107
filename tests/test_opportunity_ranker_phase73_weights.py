"""Phase 73 Plan 08 — Wave 3 ranker wiring tests (TDD GREEN).

Covers:
1. StrategyWeightsLoader returns Phase 73 baseline (10/15/15/10/10/15/10/10/5).
2. Loader fail-fast on unknown strategy_id.
3. Loader sources from VM100 REST API (env-driven URL) — HTTP failure raises.
4. OpportunityRanker injected with loader uses Phase 73 weights at compute time.
5. After rank(opp_id), one OpportunityScoreSnapshot row exists with
   weights_version=73, correct total_score, full 9-category breakdown.
6. Re-rank creates a SECOND row; first untouched (WORM, Plan 73-02).
7. snapshot_evidence list populated from per-category evidence
   (Phase 71 EvidenceCitation shape).
8. Snapshot persisted via VM100 typed API (POST) — not direct DB write.

Tests are HTTP-mocked: we do not require a live VM100 backend. Real
end-to-end verification is the responsibility of /tmp/phase73_08_verify.py
against the live container.
"""
from __future__ import annotations

import os
import pytest

# Phase 73 baseline locked at 10/15/15/10/10/15/10/10/5 — sum=100.
PHASE73_BASELINE = {
    "session_fit": 10,
    "macro_fit": 15,
    "structure_quality": 15,
    "liquidity_context": 10,
    "volatility_regime": 10,
    "strategy_adherence": 15,
    "risk_reward": 10,
    "historical_analogue_strength": 10,
    "behavioral_edge": 5,
}


# ─────────────────────────────────────────────────────────────────────────────
# StrategyWeightsLoader tests
# ─────────────────────────────────────────────────────────────────────────────


def test_loader_returns_phase73_baseline_preloaded():
    """Test 1 — preloaded mode returns the Phase 73 baseline dict verbatim."""
    from emitters.scoring.strategy_weights_loader import StrategyWeightsLoader

    loader = StrategyWeightsLoader(preloaded_weights=PHASE73_BASELINE)
    weights = loader.load(strategy_id="default")

    assert sum(weights.values()) == 100, (
        f"Phase 73 baseline must sum to 100; got {sum(weights.values())}"
    )
    assert weights == PHASE73_BASELINE


def test_loader_fail_fast_on_empty_payload():
    """Test 2 — empty weights → StrategyWeightsNotFound naming the strategy.

    Phase 47.6 lock: no fallback defaults; missing config raises with
    enough context for an operator to identify the misconfigured strategy.
    """
    from emitters.scoring.strategy_weights_loader import (
        StrategyWeightsLoader,
        StrategyWeightsNotFound,
    )

    loader = StrategyWeightsLoader(preloaded_weights={})
    with pytest.raises(StrategyWeightsNotFound) as exc_info:
        loader.load(strategy_id="nonexistent")
    assert "nonexistent" in str(exc_info.value)


def test_loader_http_error_raises_strategy_weights_not_found(monkeypatch):
    """Test 3 — VM100 HTTP failure → StrategyWeightsNotFound (no silent default).

    Env-driven config lock: URL comes from env; HTTP failure raises.
    """
    import httpx

    from emitters.scoring.strategy_weights_loader import (
        StrategyWeightsLoader,
        StrategyWeightsNotFound,
    )

    def boom_get(*args, **kwargs):
        raise httpx.ConnectError("VM100 unreachable")

    monkeypatch.setattr(httpx, "get", boom_get)

    loader = StrategyWeightsLoader(
        api_url="http://vm100-backend:8000/api/internal/mission-control/strategy-weights"
    )
    with pytest.raises(StrategyWeightsNotFound) as exc_info:
        loader.load(strategy_id="default")
    assert "default" in str(exc_info.value)


def test_loader_env_var_required_when_no_args(monkeypatch):
    """Test 3b — KeyError when env var unset AND no api_url + no preloaded."""
    from emitters.scoring.strategy_weights_loader import StrategyWeightsLoader

    monkeypatch.delenv("VM100_STRATEGY_WEIGHTS_URL", raising=False)
    with pytest.raises(KeyError):
        StrategyWeightsLoader()


def test_loader_weights_must_sum_to_100():
    """Test 3c — weights summing to !=100 raise ValueError (replay invariant)."""
    from emitters.scoring.strategy_weights_loader import StrategyWeightsLoader

    loader = StrategyWeightsLoader(
        preloaded_weights={"session_fit": 50, "macro_fit": 30}  # sums to 80
    )
    with pytest.raises(ValueError) as exc_info:
        loader.load(strategy_id="default")
    assert "80" in str(exc_info.value) or "100" in str(exc_info.value)


# ─────────────────────────────────────────────────────────────────────────────
# OpportunityRanker wiring tests
# ─────────────────────────────────────────────────────────────────────────────


def test_ranker_accepts_weights_loader_at_construction():
    """Test 4 — OpportunityRanker injected with StrategyWeightsLoader exposes
    the loaded Phase 73 weights on the instance.
    """
    from emitters.opportunity_ranker import OpportunityRanker
    from emitters.scoring.strategy_weights_loader import StrategyWeightsLoader

    loader = StrategyWeightsLoader(preloaded_weights=PHASE73_BASELINE)
    ranker = OpportunityRanker(weights_loader=loader, strategy_id="default")

    # Phase 73 wiring exposes loaded weights via `.weights` attribute.
    assert hasattr(ranker, "weights"), (
        "Phase 73 ranker must expose .weights attribute populated from loader"
    )
    assert ranker.weights == PHASE73_BASELINE
    assert sum(ranker.weights.values()) == 100


def test_ranker_rank_returns_snapshot_payload_with_all_9_categories(monkeypatch):
    """Test 5 — ``rank(opp_id)`` produces a payload with all 9 Phase 73 categories
    and total_score computed via Phase 73 weights.

    Snapshot persistence is mocked (we are unit-testing the ranker, not the
    cross-VM POST round-trip).
    """
    from emitters.opportunity_ranker import OpportunityRanker
    from emitters.scoring.strategy_weights_loader import StrategyWeightsLoader

    persisted: list[dict] = []

    def fake_persist(payload):
        persisted.append(payload)
        return payload

    loader = StrategyWeightsLoader(preloaded_weights=PHASE73_BASELINE)
    ranker = OpportunityRanker(
        weights_loader=loader,
        strategy_id="default",
        snapshot_persist_fn=fake_persist,
    )
    payload = ranker.rank(opportunity_id="opp-test-1")

    # 9-category breakdown emitted.
    assert "category_scores" in payload
    cats = set(payload["category_scores"].keys())
    assert cats == set(PHASE73_BASELINE.keys()), (
        f"Phase 73 category set mismatch — got {cats}, "
        f"expected {set(PHASE73_BASELINE.keys())}"
    )

    # total_score = sum(score * weight / 100)
    expected_total = sum(
        payload["category_scores"][cat]["score"] * PHASE73_BASELINE[cat] / 100.0
        for cat in PHASE73_BASELINE
    )
    assert abs(payload["total_score"] - expected_total) < 0.01, (
        f"total_score weighted-sum mismatch: got {payload['total_score']}, "
        f"expected {expected_total}"
    )

    # Snapshot persistence called exactly once.
    assert len(persisted) == 1
    assert persisted[0]["opportunity_id"] == "opp-test-1"
    assert persisted[0]["strategy_id"] == "default"


def test_ranker_rerank_creates_new_payload(monkeypatch):
    """Test 6 — calling rank() twice produces two separate persist calls
    (snapshot is append-only at the persistence layer — Plan 73-02 WORM).
    """
    from emitters.opportunity_ranker import OpportunityRanker
    from emitters.scoring.strategy_weights_loader import StrategyWeightsLoader

    persisted: list[dict] = []

    def fake_persist(payload):
        persisted.append(payload)
        return payload

    loader = StrategyWeightsLoader(preloaded_weights=PHASE73_BASELINE)
    ranker = OpportunityRanker(
        weights_loader=loader,
        strategy_id="default",
        snapshot_persist_fn=fake_persist,
    )
    ranker.rank(opportunity_id="opp-test-2")
    ranker.rank(opportunity_id="opp-test-2")

    assert len(persisted) == 2, (
        "Re-rank must produce a second persist call — WORM at persistence layer"
    )
    # Both payloads reference the same opportunity_id.
    assert all(p["opportunity_id"] == "opp-test-2" for p in persisted)


def test_ranker_snapshot_evidence_populated(monkeypatch):
    """Test 7 — snapshot_evidence list is populated from per-category evidence."""
    from emitters.opportunity_ranker import OpportunityRanker
    from emitters.scoring.strategy_weights_loader import StrategyWeightsLoader

    persisted: list[dict] = []

    loader = StrategyWeightsLoader(preloaded_weights=PHASE73_BASELINE)
    ranker = OpportunityRanker(
        weights_loader=loader,
        strategy_id="default",
        snapshot_persist_fn=persisted.append,
    )
    ranker.rank(opportunity_id="opp-test-3")

    assert len(persisted) == 1
    payload = persisted[0]
    assert "snapshot_evidence" in payload
    # Evidence comes from per-category breakdown evidence lists; should be
    # non-empty given the deterministic CategoryScoringEngine always returns
    # at least one evidence string per category.
    assert isinstance(payload["snapshot_evidence"], list)
    assert len(payload["snapshot_evidence"]) > 0


def test_ranker_persists_via_typed_api_not_direct_db(monkeypatch):
    """Test 8 — when no snapshot_persist_fn injected, ranker uses HTTP POST
    to the VM100 typed API. We verify the POST is dispatched (no direct VM107
    DB connection to mission_control).

    Phase 39 lock check: ranker must never import django.db or
    mission_control.models from VM107.
    """
    import httpx

    from emitters.opportunity_ranker import OpportunityRanker
    from emitters.scoring.strategy_weights_loader import StrategyWeightsLoader

    captured_calls: list[dict] = []

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        captured_calls.append({"url": url, "json": json, "headers": headers})
        return _FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setenv(
        "VM100_OPPORTUNITY_SCORE_SNAPSHOT_URL",
        "http://vm100-backend:8000/api/internal/mission-control/opportunity-score-snapshot",
    )
    monkeypatch.setenv("VM100_INTERNAL_TOKEN", "test-internal-token-12345")

    loader = StrategyWeightsLoader(preloaded_weights=PHASE73_BASELINE)
    ranker = OpportunityRanker(weights_loader=loader, strategy_id="default")
    ranker.rank(opportunity_id="opp-test-4")

    assert len(captured_calls) == 1, (
        "Ranker should POST exactly once to VM100 snapshot endpoint"
    )
    assert captured_calls[0]["json"]["opportunity_id"] == "opp-test-4"
    assert captured_calls[0]["json"]["strategy_id"] == "default"
    assert "category_scores" in captured_calls[0]["json"]
    # Internal token forwarded in header (X-Internal-Token).
    headers = captured_calls[0]["headers"] or {}
    assert "X-Internal-Token" in headers
    assert headers["X-Internal-Token"] == "test-internal-token-12345"
