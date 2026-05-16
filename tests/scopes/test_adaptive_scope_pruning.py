"""Phase 62-03 Task 2 — test_adaptive_scope_pruning.py

Tests for MentorPipelineOrchestrator._prune_tools_by_adaptive_scope().

Verifies CTX-DEC-14 + Pitfall 5: prune BEFORE planning, NOT filter AFTER retrieval.

Profile scope expectations (from agent_profile YAMLs):
  - trade_auditor_agent:   adaptive_signal_categories=[]       → 0 adaptive tools
  - behavioral_mentor_agent: adaptive_signal_categories=[BEHAVIORAL] → BEHAVIORAL only
  - weekly_review_agent:  all 6 categories → all adaptive tools pass through

Covers RG-10.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


def _try_import_orchestrator():
    try:
        from helpers.mentor_pipeline_orchestrator import MentorPipelineOrchestrator
        return MentorPipelineOrchestrator
    except ImportError as exc:
        pytest.skip(f"MentorPipelineOrchestrator not importable: {exc}")


# ---------------------------------------------------------------------------
# Fixtures: candidate tools + profile memory_scope dicts
# ---------------------------------------------------------------------------

def _make_candidate_tools():
    """Return a mixed list of adaptive + non-adaptive candidate tools."""
    return [
        # Non-adaptive tool (no signal_category) — always allowed
        {"name": "get_trade_context", "signal_category": None},
        {"name": "get_behavioral_edges"},  # no signal_category key at all
        # Adaptive tools
        {"name": "get_drift_report", "signal_category": "STRATEGIC"},
        {"name": "get_behavioral_drift_summary", "signal_category": "BEHAVIORAL"},
        {"name": "get_counterfactual_scenario_stats", "signal_category": "COUNTERFACTUAL_AGGREGATE"},
        {"name": "get_pattern_clusters", "signal_category": "PATTERN"},
    ]


_TRADE_AUDITOR_SCOPE = {"adaptive_signal_categories": []}
_BEHAVIORAL_MENTOR_SCOPE = {"adaptive_signal_categories": ["BEHAVIORAL"]}
_WEEKLY_REVIEW_SCOPE = {
    "adaptive_signal_categories": [
        "BEHAVIORAL", "STRATEGIC", "REGIME", "PATTERN",
        "ADAPTIVE_RECOMMENDATION", "COUNTERFACTUAL_AGGREGATE",
    ]
}


# ---------------------------------------------------------------------------
# trade_auditor: no adaptive tools in output
# ---------------------------------------------------------------------------

def test_trade_auditor_receives_zero_adaptive_tools():
    """trade_auditor (adaptive_signal_categories=[]) → 0 adaptive tools in pruned set (RG-10)."""
    MentorPipelineOrchestrator = _try_import_orchestrator()

    candidate_tools = _make_candidate_tools()
    pruned = MentorPipelineOrchestrator._prune_tools_by_adaptive_scope(
        profile_memory_scope=_TRADE_AUDITOR_SCOPE,
        candidate_tools=candidate_tools,
    )

    # Non-adaptive tools pass through
    pruned_names = {t["name"] for t in pruned}
    assert "get_trade_context" in pruned_names
    assert "get_behavioral_edges" in pruned_names

    # Adaptive tools excluded
    assert "get_drift_report" not in pruned_names
    assert "get_behavioral_drift_summary" not in pruned_names
    assert "get_counterfactual_scenario_stats" not in pruned_names
    assert "get_pattern_clusters" not in pruned_names

    # Total: only 2 non-adaptive tools
    assert len(pruned) == 2


# ---------------------------------------------------------------------------
# behavioral_mentor: BEHAVIORAL only
# ---------------------------------------------------------------------------

def test_behavioral_mentor_receives_behavioral_only():
    """behavioral_mentor (adaptive_signal_categories=[BEHAVIORAL]) → BEHAVIORAL tools only (RG-10)."""
    MentorPipelineOrchestrator = _try_import_orchestrator()

    candidate_tools = _make_candidate_tools()
    pruned = MentorPipelineOrchestrator._prune_tools_by_adaptive_scope(
        profile_memory_scope=_BEHAVIORAL_MENTOR_SCOPE,
        candidate_tools=candidate_tools,
    )

    pruned_names = {t["name"] for t in pruned}

    # Non-adaptive pass through
    assert "get_trade_context" in pruned_names
    assert "get_behavioral_edges" in pruned_names

    # BEHAVIORAL allowed
    assert "get_behavioral_drift_summary" in pruned_names

    # Non-BEHAVIORAL adaptive excluded
    assert "get_drift_report" not in pruned_names  # STRATEGIC
    assert "get_counterfactual_scenario_stats" not in pruned_names  # COUNTERFACTUAL_AGGREGATE
    assert "get_pattern_clusters" not in pruned_names  # PATTERN

    # Total: 2 non-adaptive + 1 BEHAVIORAL = 3
    assert len(pruned) == 3


# ---------------------------------------------------------------------------
# weekly_review: all 6 categories → all adaptive tools pass through
# ---------------------------------------------------------------------------

def test_weekly_review_receives_all_adaptive_tools():
    """weekly_review (all 6 categories) → all adaptive tools pass through (RG-10)."""
    MentorPipelineOrchestrator = _try_import_orchestrator()

    candidate_tools = _make_candidate_tools()
    pruned = MentorPipelineOrchestrator._prune_tools_by_adaptive_scope(
        profile_memory_scope=_WEEKLY_REVIEW_SCOPE,
        candidate_tools=candidate_tools,
    )

    pruned_names = {t["name"] for t in pruned}

    # All tools pass through — non-adaptive + all 4 adaptive
    assert "get_trade_context" in pruned_names
    assert "get_behavioral_edges" in pruned_names
    assert "get_drift_report" in pruned_names
    assert "get_behavioral_drift_summary" in pruned_names
    assert "get_counterfactual_scenario_stats" in pruned_names
    assert "get_pattern_clusters" in pruned_names

    assert len(pruned) == len(candidate_tools)


# ---------------------------------------------------------------------------
# Empty candidate tools list → [] regardless of scope
# ---------------------------------------------------------------------------

def test_prune_with_empty_candidate_tools_returns_empty():
    """Empty candidate list → empty result regardless of profile scope."""
    MentorPipelineOrchestrator = _try_import_orchestrator()

    assert MentorPipelineOrchestrator._prune_tools_by_adaptive_scope(
        profile_memory_scope=_WEEKLY_REVIEW_SCOPE,
        candidate_tools=[],
    ) == []


# ---------------------------------------------------------------------------
# No adaptive_signal_categories key in scope → no adaptive tools
# ---------------------------------------------------------------------------

def test_missing_adaptive_signal_categories_excludes_all_adaptive():
    """Profile memory_scope with no adaptive_signal_categories key → empty allowed set."""
    MentorPipelineOrchestrator = _try_import_orchestrator()

    candidate_tools = _make_candidate_tools()
    pruned = MentorPipelineOrchestrator._prune_tools_by_adaptive_scope(
        profile_memory_scope={},  # no adaptive_signal_categories key
        candidate_tools=candidate_tools,
    )

    pruned_names = {t["name"] for t in pruned}
    assert "get_drift_report" not in pruned_names
    assert "get_behavioral_drift_summary" not in pruned_names
    assert "get_trade_context" in pruned_names  # non-adaptive always allowed
