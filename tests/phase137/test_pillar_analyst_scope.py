"""E-HIGH2 — pillar-analyst scope is a DECISION the test enforces, not a blind grant.

The four pillar analysts (growth / inflation / liquidity / risk) are narrative-only BY
DESIGN (§J Router+Synthesizer: ``max_cost_usd: 0.0``, ``is_deterministic: true``,
``allowed_tools: [lookup_capability]``, ``denied: vm102_pillar_compute``). The roadmap
calls them "under-tooled" (E-HIGH2), but granting data tools would contradict the
architecture. RESEARCH §E-HIGH2 offers two readings:

  (a) correctly scoped — grant nothing (recommended default), OR
  (b) newer design fetches supporting series — grant read-only data tools AND relax the
      narrative-only guards (a bigger change).

The decision is deferred to 137-07 (``checkpoint:human-verify``). This module keys off a
SINGLE module-level constant so 137-07 flips ONE line post-checkpoint.

RED at develop HEAD: the decision is ``unconfirmed`` — the gate test fails until 137-07
records the human-verified reading. The per-analyst scope assertions then run for the
confirmed reading.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from helpers.tool_scope import apply_tool_scope

_PROFILE_DIR = Path(__file__).resolve().parent.parent.parent / "registry" / "agent_profile"

# ── THE decision constant — 137-07 flips this ONE line after the human-verify ────
#   "unconfirmed" -> RED gate (pending checkpoint)
#   "a"           -> grant nothing (narrative-only preserved; recommended default)
#   "b"           -> grant read-only data tools + relax narrative-only guards
PILLAR_GRANT_DECISION = "unconfirmed"

PILLAR_ANALYSTS: tuple[str, ...] = (
    "vm107.growth_analyst",
    "vm107.inflation_analyst",
    "vm107.liquidity_analyst",
    "vm107.risk_analyst",
)

# The read-only data tools reading (b) would grant (RESEARCH §E-HIGH2).
DATA_TOOLS: tuple[str, ...] = (
    "get_indicator_series",
    "get_release_history",
    "get_upcoming_events",
    "get_forecast_drift",
)


def _load_profile(profile_id: str) -> dict:
    with open(_PROFILE_DIR / f"{profile_id}.yaml") as fh:
        return yaml.safe_load(fh)


def test_pillar_grant_decision_confirmed():
    """E-HIGH2 gate — the pillar grant decision must be human-verified at 137-07.

    RED until 137-07 sets PILLAR_GRANT_DECISION to the confirmed reading ("a" or "b").
    """
    assert PILLAR_GRANT_DECISION in ("a", "b"), (
        "E-HIGH2 pillar-analyst grant decision is unconfirmed — resolve the "
        "137-07 checkpoint:human-verify (reading (a) grant-nothing [default] vs "
        "(b) grant read-only data tools), then flip PILLAR_GRANT_DECISION"
    )


@pytest.mark.parametrize("profile_id", PILLAR_ANALYSTS)
def test_pillar_analyst_scope_matches_decision(profile_id, reg):
    """Assert each pillar analyst's scope matches the CONFIRMED reading (a) or (b)."""
    if PILLAR_GRANT_DECISION not in ("a", "b"):
        pytest.skip("pillar grant decision pending 137-07 checkpoint")

    prof = _load_profile(profile_id)
    allowed = prof.get("allowed_tools") or []

    if PILLAR_GRANT_DECISION == "a":
        # Narrative-only preserved: scope stays [lookup_capability]; guards unchanged.
        assert allowed == ["lookup_capability"], (
            f"{profile_id}: reading (a) requires allowed_tools == [lookup_capability], "
            f"got {allowed!r}"
        )
        assert prof.get("max_cost_usd") == 0.0, (
            f"{profile_id}: narrative-only guard max_cost_usd must stay 0.0 under reading (a)"
        )
        assert prof.get("is_deterministic") is True, (
            f"{profile_id}: narrative-only guard is_deterministic must stay true under (a)"
        )
    else:  # reading (b)
        index = reg.get_index_for_profile(profile_id)
        advertised = {e["id"] for e in apply_tool_scope(
            index, prof.get("allowed_tools"), prof.get("denied_tools")
        )}
        for tool_id in DATA_TOOLS:
            assert tool_id in advertised, (
                f"{profile_id}: reading (b) requires {tool_id!r} advertised (both surfaces)"
            )
        assert prof.get("max_cost_usd", 0.0) > 0.0, (
            f"{profile_id}: reading (b) relaxes max_cost_usd above 0.0 for tool calls"
        )
