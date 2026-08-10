"""E-CRIT1 / D-02 — no-capability-regression gate over the empty-aap audit set.

D-01 flips ``index.py`` to fail-closed (empty ``allowed_agent_profiles`` -> deny). The
MANDATORY guard (D-02) is that every tool riding the allow-all default today gets an
EXPLICIT grant so net capability does NOT regress. RESEARCH §4 enumerates the 15-tool
audit set; ``response`` is the #1 regression risk (Pitfall 1 — it is the universal reply
tool and goes dark for EVERY agent under D-01 unless granted).

This module encodes that audit set as data and asserts, through the real hops
(``apply_tool_scope(get_index_for_profile(grantee))``), that each intended tool is
ADVERTISED to its intended grantee.

Gate ordering (intended): RED today because the canonical-id grants + tool-side aap
grants are not landed yet; goes green when 137-04 adds the grants AND 137-06 flips the
deny. ``response`` rides allow-all today (green) and must STAY advertised after the flip
— that is the regression it guards.

Analog: tests/phase135/test_scope_from_registry.py (assertion shape).
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from helpers.tool_scope import apply_tool_scope

_PROFILE_DIR = Path(__file__).resolve().parent.parent.parent / "registry" / "agent_profile"


def _load_profile(profile_id: str) -> dict:
    path = _PROFILE_DIR / f"{profile_id}.yaml"
    with open(path) as fh:
        return yaml.safe_load(fh)


def _all_profiles() -> list[dict]:
    profiles = []
    for path in sorted(_PROFILE_DIR.glob("*.yaml")):
        with open(path) as fh:
            data = yaml.safe_load(fh)
        if isinstance(data, dict) and data.get("id"):
            profiles.append(data)
    return profiles


def _advertised_ids(reg, profile: dict) -> set[str]:
    index = reg.get_index_for_profile(profile["id"])
    scoped = apply_tool_scope(index, profile.get("allowed_tools"), profile.get("denied_tools"))
    return {e["id"] for e in scoped}


# RESEARCH §4 — the 15-tool empty-aap D-02 audit set (canonical ids). Presence lock:
# every one must remain a registered capability (none silently deleted).
FULL_AUDIT_SET: tuple[str, ...] = (
    "response",
    "get_indicator_series",
    "get_release_history",
    "get_upcoming_events",
    "get_forecast_drift",
    "vm102.indicator_history",
    "vm102.indicator_event_study",
    "vm102.indicator_correlations",
    "vm102.indicator_distribution",
    "vm102.indicator_asset_exposure",
    "vm102.indicator_regime",
    "vm102.indicator_releases",
    "vm107.lookup_reasoning_artifact",
    "vm107.mcp_server",
    "vm107.tool.manage_watchlist",
)

# The confirmed (tool_id, intended_grantee) grants from RESEARCH §4 whose advertising is
# a hard regression contract. Rows marked "(confirm)" in §4 are intentionally excluded
# here (grantee not yet pinned) — they are covered by the FULL_AUDIT_SET presence lock.
CONFIRMED_GRANTS: tuple[tuple[str, str], ...] = (
    ("get_indicator_series", "vm107.macro_investigator"),
    ("get_release_history", "vm107.macro_investigator"),
    ("get_upcoming_events", "vm107.macro_investigator"),
    ("get_forecast_drift", "vm107.macro_investigator"),
    ("vm102.indicator_history", "vm107.macro_investigator"),
    ("vm102.indicator_event_study", "vm107.macro_investigator"),
    ("vm102.indicator_correlations", "vm107.macro_investigator"),
    ("vm102.indicator_distribution", "vm107.macro_investigator"),
    ("vm102.indicator_asset_exposure", "vm107.macro_asset_exposure_analyst"),
    ("vm107.lookup_reasoning_artifact", "vm107.macro_investigator"),
)


@pytest.mark.parametrize("tool_id", FULL_AUDIT_SET)
def test_audit_set_tools_still_registered(tool_id, reg):
    """Presence lock: no D-02 audit-set tool is silently deleted (additive-only D-07)."""
    assert reg._by_id.get(tool_id) is not None, (
        f"D-02 audit-set tool {tool_id!r} is not a registered capability — "
        f"net capability regressed"
    )


def test_response_stays_advertised_to_every_grantee(reg):
    """Pitfall 1 — the #1 regression: ``response`` must be advertised to EVERY profile
    that lists it in allowed_tools (it is the universal reply tool)."""
    offenders: list[str] = []
    for prof in _all_profiles():
        if "response" in (prof.get("allowed_tools") or []):
            if "response" not in _advertised_ids(reg, prof):
                offenders.append(prof["id"])
    assert not offenders, (
        "response MUST stay advertised to every profile that grants it (D-02 Pitfall 1); "
        f"dark for: {offenders}"
    )


@pytest.mark.parametrize("tool_id,grantee", CONFIRMED_GRANTS, ids=lambda v: v)
def test_audit_tool_advertised_to_intended_grantee(tool_id, grantee, reg):
    """Each confirmed D-02 grant must be ADVERTISED to its intended grantee.

    RED today for the four ``get_*`` data tools + ``vm107.lookup_reasoning_artifact``
    (not yet granted by canonical id / tool-side aap); goes green when 137-04/137-06 land.
    """
    prof = _load_profile(grantee)
    advertised = _advertised_ids(reg, prof)
    assert tool_id in advertised, (
        f"{grantee}: D-02 tool {tool_id!r} must be advertised (both surfaces) — "
        f"add the canonical id to allowed_tools AND {grantee!r} to the tool's "
        f"allowed_agent_profiles"
    )
