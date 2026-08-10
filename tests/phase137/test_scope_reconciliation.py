"""E-CRIT2 (+ SC-3, E-MED1/D-03) — the both-surfaces reconciliation gate.

THE Nyquist gate for the phase. Parametrized over every
``registry/agent_profile/*.yaml``; for each ``allowed_tools`` grant it asserts the
two-surface invariant P5 must restore (RESEARCH §2):

    for every (profile, tool) grant:
        (a) the grant resolves to a canonical tool ``id``      (D-04, no name != id)
        (b) it exec-authorizes  via check_tool_scope_for_profile (the sole gate)
        (c) it is advertised    via apply_tool_scope(get_index_for_profile(pid))

Assertions route through the REAL runtime hops only — CapabilityRegistry,
helpers.tool_scope.apply_tool_scope, helpers.tool_scope_guard.check_tool_scope_for_profile
(RESEARCH §Don't Hand-Roll). No re-implemented parser.

RED at develop HEAD for the RIGHT reasons:
  * name != id grants (e.g. ``lookup_reasoning_artifact`` vs the canonical
    ``vm107.lookup_reasoning_artifact``, ``get_domain_health`` vs
    ``vm107.tool.get_domain_health``) fail (a);
  * grants to a non-empty-aap tool that does not list the profile (e.g.
    research_chat_agent's behavioral tools) fail (c) — index.py allow-all only rescues
    EMPTY-aap tools.

Deferred grants recorded in RESEARCH §E-CRIT2.C (the "ghost" set, executed in P6 /
Phase 138, NOT P5) are excluded from (a)/(b)/(c) so the suite can reach green when P5
lands — the ghost boundary itself is locked separately in test_no_ghost_grants.py.

Analog: tests/phase135/test_scope_from_registry.py + RESEARCH §Code Examples skeleton.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from helpers.tool_scope import apply_tool_scope
from helpers.tool_scope_guard import check_tool_scope_for_profile

_PROFILE_DIR = Path(__file__).resolve().parent.parent.parent / "registry" / "agent_profile"

# RESEARCH §E-CRIT2.C — the 14 recorded ghost grants. P5 records restore-vs-delete only;
# P6 / Phase 138 executes. Excluded from the both-surfaces assertion so P5 can go green
# without wiring capabilities that are deliberately out of scope this phase.
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


def _load_profiles() -> list[dict]:
    profiles: list[dict] = []
    for path in sorted(_PROFILE_DIR.glob("*.yaml")):
        with open(path) as fh:
            data = yaml.safe_load(fh)
        if isinstance(data, dict) and data.get("id"):
            profiles.append(data)
    return profiles


_PROFILES = _load_profiles()


def test_registry_has_all_profiles():
    """Sanity: the 66 authoritative agent-profile yamls loaded (collection guard)."""
    assert len(_PROFILES) >= 60, (
        f"expected the full agent_profile set, loaded {len(_PROFILES)} from {_PROFILE_DIR}"
    )


@pytest.mark.parametrize("prof", _PROFILES, ids=lambda p: p["id"])
def test_advertised_equals_authorized(prof, reg):
    """Both-surfaces reconciliation for every non-ghost grant in a profile (E-CRIT2/SC-3).

    (a) canonical id, (b) exec-authorized, (c) advertised — all via the real hops.
    """
    pid = prof["id"]
    allowed = prof.get("allowed_tools")
    denied = prof.get("denied_tools")

    index = reg.get_index_for_profile(pid)
    advertised = {e["id"] for e in apply_tool_scope(index, allowed, denied)}

    for tool_id in (allowed or []):
        if tool_id in GHOST_ALLOWLIST:
            # Recorded deferral (RESEARCH §E-CRIT2.C) — P6/Phase 138 executes; not P5.
            continue

        # (a) the grant is a canonical, namespaced tool id (D-04) — name != id vanishes here.
        assert reg._by_id.get(tool_id) is not None, (
            f"{pid}: grant {tool_id!r} is not a canonical tool id "
            f"(name != id? normalize per RESEARCH §E-CRIT2.A)"
        )

        # (b) it exec-authorizes through the sole dispatch gate.
        assert check_tool_scope_for_profile(tool_id, prof) is None, (
            f"{pid}: {tool_id!r} granted in allowed_tools but exec-DENIED by "
            f"check_tool_scope_for_profile"
        )

        # (c) it is advertised — tool.allowed_agent_profiles must include pid.
        assert tool_id in advertised, (
            f"{pid}: {tool_id!r} authorized but NOT advertised "
            f"(tool.allowed_agent_profiles missing {pid!r} — Pitfall 2)"
        )


# ── E-MED1 / D-03 — allowed_tools:[] + non-empty denied_tools = zero tools ───────


def test_empty_allowed_with_denied_advertises_nothing_contract():
    """D-03 contract, asserted directly through apply_tool_scope (deterministic).

    A profile whose ``allowed_tools`` is ``[]`` (present-but-empty) advertises ZERO
    tools regardless of ``denied_tools`` content — the documented zero-tools contract.
    """
    sample_index = [
        {"id": "response", "short_description": "", "impact_on_decision": "HIGH"},
        {"id": "lookup_capability", "short_description": "", "impact_on_decision": "LOW"},
    ]
    advertised = apply_tool_scope(sample_index, [], ["response"])
    assert advertised == [], (
        "allowed_tools:[] must yield an EMPTY advertised set (E-MED1/D-03), "
        f"got {advertised!r}"
    )


def test_real_profiles_with_empty_allowed_and_denied_advertise_nothing(reg):
    """D-03 over the live registry: any profile with allowed_tools:[] + denied != []
    advertises nothing. Passes vacuously if no such profile exists (contract lock)."""
    for prof in _PROFILES:
        allowed = prof.get("allowed_tools")
        denied = prof.get("denied_tools")
        if allowed == [] and denied:
            index = reg.get_index_for_profile(prof["id"])
            advertised = apply_tool_scope(index, allowed, denied)
            assert advertised == [], (
                f"{prof['id']}: allowed_tools:[] must advertise zero tools "
                f"(E-MED1/D-03), got {[e['id'] for e in advertised]!r}"
            )
