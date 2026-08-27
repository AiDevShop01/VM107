"""Phase 168 Plan 03 Task 1 — token-budget estimator + per-tier caps + L0->L4 ladder.

Proves the Contract §6 tool-economy sub-contract (COMPACT/STANDARD/DETAILED/RAW),
the effective-cap = min(tier, profile) rule, the mark-partial-on-truncation contract
(a tool MUST NOT silently drop data), and strictly-widening progressive disclosure.

Host-clean: imports only `core.evidence.tools.budget` (pure — pydantic + stdlib).
"""
from __future__ import annotations

from core.evidence.tools import budget


# ---------------------------------------------------------------------------
# Tier caps == Contract §6 (agent-catalogue/01 §6)
# ---------------------------------------------------------------------------


def test_tier_caps_match_contract_section6():
    assert budget.COMPACT == 250
    assert budget.STANDARD == 750
    assert budget.DETAILED == 2000
    assert budget.RAW is None  # explicit-only, no numeric cap
    assert budget.TIER_CAPS == {
        "COMPACT": 250,
        "STANDARD": 750,
        "DETAILED": 2000,
        "RAW": None,
    }


def test_detail_tiers_order_is_compact_to_raw():
    assert budget.DETAIL_TIERS == ("COMPACT", "STANDARD", "DETAILED", "RAW")


# ---------------------------------------------------------------------------
# next_detail_levels — strictly widening only
# ---------------------------------------------------------------------------


def test_next_detail_levels_strictly_widening():
    assert budget.next_detail_levels("COMPACT") == ("STANDARD", "DETAILED", "RAW")
    assert budget.next_detail_levels("STANDARD") == ("DETAILED", "RAW")
    assert budget.next_detail_levels("DETAILED") == ("RAW",)
    assert budget.next_detail_levels("RAW") == ()


def test_next_detail_levels_rejects_unknown_tier():
    import pytest

    with pytest.raises(ValueError):
        budget.next_detail_levels("HUGE")


# ---------------------------------------------------------------------------
# estimate_tokens — deterministic + monotonic on payload size
# ---------------------------------------------------------------------------


def test_estimate_tokens_deterministic_and_monotonic():
    small = {"percentile": 71.4}
    large = {"percentile": 71.4, "note": "x" * 4000}
    t_small = budget.estimate_tokens(small)
    assert t_small == budget.estimate_tokens(small)  # deterministic
    assert budget.estimate_tokens(large) > t_small  # bigger payload => more tokens


def test_estimate_tokens_accepts_pydantic_payload():
    from pydantic import BaseModel

    class _P(BaseModel):
        percentile: float

    assert budget.estimate_tokens(_P(percentile=71.4)) > 0


# ---------------------------------------------------------------------------
# effective_cap = min(tier cap, profile max_tool_result_tokens)
# ---------------------------------------------------------------------------


def test_effective_cap_is_min_of_tier_and_profile():
    assert budget.effective_cap("STANDARD", None) == 750
    assert budget.effective_cap("STANDARD", 300) == 300  # profile tightens
    assert budget.effective_cap("STANDARD", 900) == 750  # profile cannot loosen
    # RAW has no tier cap, but a profile MAY still bound it.
    assert budget.effective_cap("RAW", None) is None
    assert budget.effective_cap("RAW", 500) == 500


# ---------------------------------------------------------------------------
# enforce_budget — success under cap, partial (never silent-drop) over cap
# ---------------------------------------------------------------------------


def test_enforce_budget_success_when_under_cap():
    d = budget.enforce_budget({"percentile": 71.4}, "COMPACT")
    assert d.outcome_class == "success"
    assert d.truncated is False
    assert d.effective_cap == 250
    assert d.estimated_tokens <= d.effective_cap


def test_enforce_budget_marks_partial_when_over_cap():
    # ~1000 tokens — far over the COMPACT 250 cap.
    d = budget.enforce_budget({"blob": "x" * 4000}, "COMPACT")
    assert d.outcome_class == "partial"  # NOT "success" — no silent drop
    assert d.truncated is True
    assert d.estimated_tokens > d.effective_cap


def test_profile_cap_tighter_than_tier_triggers_partial():
    # ~400 tokens: under STANDARD (750) but over the profile cap (300).
    d = budget.enforce_budget({"note": "y" * 1600}, "STANDARD", profile_cap=300)
    assert d.effective_cap == 300
    assert d.outcome_class == "partial"
    assert d.truncated is True


def test_raw_tier_never_truncates_without_profile_cap():
    d = budget.enforce_budget({"note": "z" * 40000}, "RAW")
    assert d.effective_cap is None
    assert d.outcome_class == "success"
    assert d.truncated is False


# ---------------------------------------------------------------------------
# merge_detail_fields — progressive disclosure L0->L4 widens monotonically
# ---------------------------------------------------------------------------


def test_merge_detail_fields_widens_monotonically():
    fields_by_tier = {
        "COMPACT": {"a": 1},
        "STANDARD": {"b": 2},
        "DETAILED": {"c": 3},
        "RAW": {"d": 4},
    }
    compact = budget.merge_detail_fields(fields_by_tier, "COMPACT")
    standard = budget.merge_detail_fields(fields_by_tier, "STANDARD")
    detailed = budget.merge_detail_fields(fields_by_tier, "DETAILED")
    raw = budget.merge_detail_fields(fields_by_tier, "RAW")

    # strictly widening supersets
    assert set(compact) < set(standard) < set(detailed) < set(raw)
    assert compact == {"a": 1}
    assert raw == {"a": 1, "b": 2, "c": 3, "d": 4}
