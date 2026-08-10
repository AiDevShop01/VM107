"""SC-3 contract — no ghost grants beyond the recorded RESEARCH §E-CRIT2.C set.

Locks the ghost boundary so P5 (and P6 scope) cannot silently widen. Every
``allowed_tools`` grant across all 66 profiles must be one of:

  1. a canonical registered tool ``id`` (``reg._by_id``), OR
  2. a name that normalizes to a canonical id — RESEARCH §E-CRIT2.A (tool EXISTS,
     grant uses name/stem; P5 rewrites to the id), OR
  3. a name backed by a ``tools/*.py`` module awaiting registration — §E-CRIT2.B
     (RESTORE targets), OR
  4. an explicitly recorded ghost — RESEARCH §E-CRIT2.C (the 14-entry deferred set;
     P6 / Phase 138 decides restore-vs-delete, P5 records only).

Any grant outside ALL four buckets is an UNRECORDED ghost and FAILS — forcing a research
pass rather than silent widening. This test is a boundary lock (green when the audit is
complete); a failure means a grant slipped the §E-CRIT2 audit.

Analog: tests/phase135/test_scope_from_registry.py (assertion shape).
"""
from __future__ import annotations

from pathlib import Path

import yaml

_PROFILE_DIR = Path(__file__).resolve().parent.parent.parent / "registry" / "agent_profile"

# §E-CRIT2.A — grants that use a tool NAME/stem; the tool exists, P5 normalizes to the id.
NORMALIZE_NAMES: frozenset[str] = frozenset({
    "get_domain_health",
    "lookup_reasoning_artifact",
    "fetch_replay_frame",
    "lookup_replay_artifact",
    "behavioral_analysis",
    "execution_quality",
    "find_countries_by_profile_query",
})

# §E-CRIT2.B — grants backed by a tools/*.py module but no registry yaml (RESTORE targets).
RESTORE_NAMES: frozenset[str] = frozenset({
    "search_knowledge",
    "skills_tool",
    "document_query",
    "get_performance_history",
    "get_regime_context",
})

# §E-CRIT2.C — the 14 recorded ghosts (P6 / Phase 138 executes; P5 records only).
# MUST match RESEARCH §E-CRIT2.C exactly — no silent widening.
GHOST_ALLOWLIST: frozenset[str] = frozenset({
    "belief_store.propose",
    "belief_store.query",
    "episodic_memory_service.query",
    "phase71.evidence_drawer.write",
    "phase87.regime_state_reader",
    "phase89.correlation_data_reader",
    "phase90.forecast_market_impact",
    "phase91.alert_candidate_emit",
    "vm102.event_study",
    "vm102.indicator_lead_lag",
    "vm102_forecast_indicator",
    "vm102_forecast_market_impact",
    "vm102_forecast_regime",
    "vm102_forecast_surprise",
})

_RECORDED_NON_CANONICAL = NORMALIZE_NAMES | RESTORE_NAMES | GHOST_ALLOWLIST


def _all_grants() -> dict[str, set[str]]:
    """Map each distinct allowed_tools grant -> the set of profiles that reference it."""
    grants: dict[str, set[str]] = {}
    for path in sorted(_PROFILE_DIR.glob("*.yaml")):
        with open(path) as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict) or not data.get("id"):
            continue
        for tool in (data.get("allowed_tools") or []):
            grants.setdefault(tool, set()).add(data["id"])
    return grants


def test_ghost_allowlist_matches_research_exactly():
    """§E-CRIT2.C is exactly 14 recorded ghosts (guard against silent list drift)."""
    assert len(GHOST_ALLOWLIST) == 14, (
        f"§E-CRIT2.C ghost set must be exactly 14 entries, got {len(GHOST_ALLOWLIST)}"
    )


def test_no_unrecorded_ghost_grants(reg):
    """Every grant is a canonical id or a recorded §A/§B/§C exception — nothing else."""
    canonical_ids = set(reg._by_id.keys())
    unrecorded: dict[str, list[str]] = {}
    for grant, profiles in _all_grants().items():
        if grant in canonical_ids or grant in _RECORDED_NON_CANONICAL:
            continue
        unrecorded[grant] = sorted(profiles)

    assert not unrecorded, (
        "unrecorded ghost grants found (neither a canonical id, a §E-CRIT2.A/.B "
        "normalize/restore target, nor a §E-CRIT2.C recorded ghost). Add to the research "
        f"audit before P6 — do NOT silently widen:\n{unrecorded}"
    )
