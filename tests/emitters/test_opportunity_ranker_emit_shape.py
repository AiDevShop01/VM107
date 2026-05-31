"""Phase 73 follow-up regression — OpportunityRanker emit-shape contract.

Locks the wire shape of ``OpportunityRanker.rank_opportunities`` against the
canonical ``OpportunityRankingSnapshotContract`` /
``OpportunityTierContract`` types defined in
``mission_control.contracts.opportunity``.

Why these tests exist:
    Prior to 2026-05-31 the emitter shipped a v1 shape that used
    ``opportunities`` (not ``rankings``), ``tier`` (not ``assigned_tier``),
    and omitted ``opportunity_id`` / ``instrument_id`` / ``direction``
    entirely. That silently broke the DEFERRED-73-K aggregator-side seeder
    (it skipped every entry for missing IDs) and the VM100 OpportunityCard
    rendered an empty ribbon. These tests prevent that regression.

Coverage:
    1. ``rankings`` key present at top level (not legacy ``opportunities``)
    2. Each entry exposes a UUID-parseable ``opportunity_id``
    3. Each entry exposes a UUID-parseable ``instrument_id`` that is
       stable across calls for the same symbol
    4. Each entry uses ``assigned_tier`` (not legacy ``tier``)
    5. ``opportunity_id`` is stable across re-emit for the same
       (account_id, symbol, strategy) tuple — critical for lifecycle
       continuity across tier flips (WATCH ↔ DEV ↔ A+).
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.phase_66

from emitters.opportunity_ranker import OpportunityRanker  # noqa: E402


def _stub_universe(symbols):
    return [type("_Inst", (), {"symbol": s})() for s in symbols]


def _make_ranker_with_universe(symbols):
    ranker = OpportunityRanker()
    return ranker, _stub_universe(symbols)


def test_emit_uses_canonical_rankings_key_not_opportunities():
    """Canonical contract key is ``rankings``; legacy ``opportunities`` must be gone."""
    ranker, universe = _make_ranker_with_universe(["EURUSD", "GBPUSD"])
    with patch.object(ranker, "_fetch_universe", return_value=universe), \
         patch.object(ranker, "_persist_snapshot"):
        snapshot = ranker.rank_opportunities(state="mid", account_id=1)

    assert "rankings" in snapshot, "Snapshot must use canonical 'rankings' key"
    assert "opportunities" not in snapshot, (
        "Snapshot must NOT use legacy 'opportunities' key — VM100 aggregator "
        "reads 'rankings' per OpportunityRankingSnapshotContract."
    )
    assert isinstance(snapshot["rankings"], list)
    assert len(snapshot["rankings"]) == 2


def test_each_entry_has_uuid_parseable_opportunity_id():
    """Every ranking entry MUST carry a parseable opportunity_id UUID."""
    ranker, universe = _make_ranker_with_universe(["EURUSD", "USDJPY"])
    with patch.object(ranker, "_fetch_universe", return_value=universe), \
         patch.object(ranker, "_persist_snapshot"):
        snapshot = ranker.rank_opportunities(state="mid", account_id=1)

    for entry in snapshot["rankings"]:
        opp_id = entry.get("opportunity_id")
        assert opp_id, "opportunity_id must be present and non-empty"
        # uuid.UUID raises ValueError on malformed strings — required by seeder.
        parsed = uuid.UUID(str(opp_id))
        assert parsed.version == 5, (
            "opportunity_id must be UUID5 (deterministic from "
            "(account_id, symbol, strategy))"
        )


def test_each_entry_has_stable_instrument_id_keyed_on_symbol():
    """instrument_id must be UUID5 keyed on symbol and stable across calls."""
    ranker, universe = _make_ranker_with_universe(["EURUSD", "GBPUSD"])
    with patch.object(ranker, "_fetch_universe", return_value=universe), \
         patch.object(ranker, "_persist_snapshot"):
        snap1 = ranker.rank_opportunities(state="mid", account_id=1)
        snap2 = ranker.rank_opportunities(state="mid", account_id=42)  # different account

    iid_by_symbol_call1 = {e["symbol"]: e["instrument_id"] for e in snap1["rankings"]}
    iid_by_symbol_call2 = {e["symbol"]: e["instrument_id"] for e in snap2["rankings"]}

    for symbol in ("EURUSD", "GBPUSD"):
        assert iid_by_symbol_call1[symbol] == iid_by_symbol_call2[symbol], (
            f"instrument_id for {symbol!r} must be symbol-keyed and stable across "
            f"emits regardless of account_id; got "
            f"{iid_by_symbol_call1[symbol]} vs {iid_by_symbol_call2[symbol]}"
        )
        # And it must be parseable UUID5.
        parsed = uuid.UUID(iid_by_symbol_call1[symbol])
        assert parsed.version == 5


def test_each_entry_uses_assigned_tier_not_legacy_tier():
    """Canonical OpportunityTierContract field is ``assigned_tier``.

    Phase 66 Wave 1 v1 used ``tier``; the VM100 aggregator + OpportunityCard
    + lifecycle service all read ``assigned_tier``.
    """
    ranker, universe = _make_ranker_with_universe(["EURUSD"])
    with patch.object(ranker, "_fetch_universe", return_value=universe), \
         patch.object(ranker, "_persist_snapshot"):
        snapshot = ranker.rank_opportunities(state="mid", account_id=1)

    entry = snapshot["rankings"][0]
    assert "assigned_tier" in entry, "Entry must use canonical 'assigned_tier' key"
    assert "tier" not in entry, (
        "Entry must NOT use legacy 'tier' key — OpportunityCard + lifecycle "
        "service read 'assigned_tier' per OpportunityTierContract."
    )
    assert entry["assigned_tier"] in ("A+", "DEV", "WATCH")
    # Also confirm the other contract-required fields are present so the
    # canonical Pydantic model can be constructed downstream.
    for required in ("symbol", "direction", "strategy", "numeric_score",
                     "structural_valid", "gate_failures"):
        assert required in entry, f"Required canonical field missing: {required!r}"
    assert entry["direction"] in ("long", "short")


def test_opportunity_id_stable_across_re_emit_for_same_account_symbol_strategy():
    """Re-emit of (account_id, symbol, strategy) must yield same opportunity_id.

    Critical for Decision 8 lifecycle continuity — the seeder uses
    get_or_create(id=...), so tier-flip cases (WATCH → DEV → A+) must hit
    the SAME VM100 Opportunity row, never mint a new one.
    """
    ranker, universe = _make_ranker_with_universe(["EURUSD", "USDJPY"])
    with patch.object(ranker, "_fetch_universe", return_value=universe), \
         patch.object(ranker, "_persist_snapshot"):
        snap_a = ranker.rank_opportunities(state="mid", account_id=1)
        snap_b = ranker.rank_opportunities(state="mid", account_id=1)

    a_by_symbol = {e["symbol"]: e["opportunity_id"] for e in snap_a["rankings"]}
    b_by_symbol = {e["symbol"]: e["opportunity_id"] for e in snap_b["rankings"]}

    for symbol in ("EURUSD", "USDJPY"):
        assert a_by_symbol[symbol] == b_by_symbol[symbol], (
            f"opportunity_id for {symbol!r} must be stable across re-emit "
            f"for the same (account_id, strategy) tuple; got "
            f"{a_by_symbol[symbol]!r} vs {b_by_symbol[symbol]!r}"
        )

    # And changing account_id must change opportunity_id (different VM100 row).
    with patch.object(ranker, "_fetch_universe", return_value=universe), \
         patch.object(ranker, "_persist_snapshot"):
        snap_c = ranker.rank_opportunities(state="mid", account_id=42)
    c_by_symbol = {e["symbol"]: e["opportunity_id"] for e in snap_c["rankings"]}
    for symbol in ("EURUSD", "USDJPY"):
        assert a_by_symbol[symbol] != c_by_symbol[symbol], (
            f"opportunity_id for {symbol!r} must differ when account_id "
            f"changes — different account = different VM100 row."
        )
