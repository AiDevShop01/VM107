"""v1 B-01 — skeleton profiles carry ``status: planned`` (D-08), with a Pitfall-3 guard.

D-08: the ~8 un-implemented skeleton profiles get ``status: planned`` (not an
implementation). RESEARCH §7 gives a module-presence HEURISTIC set, NOT a final list —
Pitfall 3 warns that marking a router-dispatched profile ``planned`` removes it from the
REAL set (``index.py:44`` filters ``status != REAL``) and can 404 the dispatch. So the
exact set must be confirmed per-profile (dispatch-reachability) at the 137-07
``checkpoint:human-verify``.

This module keys off a single OVERRIDABLE flag + candidate list that 137-07 finalizes:

  * ``SKELETON_SET_CONFIRMED`` — False until the 137-07 per-profile human-verify.
  * ``SKELETON_CANDIDATES`` — the finalized skeleton ids (137-07 fills from RESEARCH §7
    after confirming each is genuinely un-dispatched).

RED at develop HEAD: the set is unconfirmed and no profile carries ``status: planned``
yet. Once confirmed, each candidate must be ``planned`` and each must NOT still be in the
REAL/dispatched set (Pitfall 3).
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_PROFILE_DIR = Path(__file__).resolve().parent.parent.parent / "registry" / "agent_profile"

# ── OVERRIDABLE by 137-07 after the per-profile dispatch-reachability human-verify ──
SKELETON_SET_CONFIRMED = False
# Finalized skeleton ids (RESEARCH §7 heuristic seed; 137-07 confirms per-profile that
# each is genuinely un-dispatched before flipping it to status: planned — Pitfall 3).
SKELETON_CANDIDATES: tuple[str, ...] = ()


def _profile_status(profile_id: str) -> str | None:
    path = _PROFILE_DIR / f"{profile_id}.yaml"
    if not path.exists():
        return None
    with open(path) as fh:
        data = yaml.safe_load(fh)
    return (data or {}).get("status")


def test_skeleton_set_confirmed():
    """v1 B-01 gate — the skeleton set + status:planned must be human-verified at 137-07.

    RED until 137-07 confirms each candidate is un-dispatched (Pitfall 3) and sets
    SKELETON_SET_CONFIRMED = True with the finalized SKELETON_CANDIDATES.
    """
    assert SKELETON_SET_CONFIRMED, (
        "skeleton profile set is unconfirmed — resolve the 137-07 checkpoint:human-verify "
        "(confirm per-profile dispatch-reachability, Pitfall 3), then set "
        "SKELETON_SET_CONFIRMED = True and finalize SKELETON_CANDIDATES"
    )


def test_confirmed_skeletons_are_planned():
    """Each confirmed skeleton profile carries ``status: planned`` (D-08)."""
    if not SKELETON_SET_CONFIRMED:
        pytest.skip("skeleton set pending 137-07 confirmation")
    assert SKELETON_CANDIDATES, "SKELETON_SET_CONFIRMED but SKELETON_CANDIDATES is empty"
    for profile_id in SKELETON_CANDIDATES:
        status = _profile_status(profile_id)
        assert status is not None, f"skeleton candidate {profile_id!r} has no profile yaml"
        assert status == "planned", (
            f"{profile_id}: skeleton profile must carry status: planned (D-08), got {status!r}"
        )


def test_confirmed_skeletons_removed_from_real_set(reg):
    """Pitfall 3 — a profile marked ``planned`` must NOT still be in the REAL dispatch set.

    ``get_index_for_profile`` returns entries only for REAL capabilities; a skeleton left
    dispatch-reachable would 404. We assert the skeleton is not itself a REAL capability id.
    """
    if not SKELETON_SET_CONFIRMED:
        pytest.skip("skeleton set pending 137-07 confirmation")
    for profile_id in SKELETON_CANDIDATES:
        entry = reg._by_id.get(profile_id)
        # If the profile is registered as a capability, it must not be REAL once planned.
        if entry is not None:
            assert str(getattr(entry.status, "value", entry.status)).lower() != "real", (
                f"{profile_id}: marked planned but still REAL in the registry (Pitfall 3 — "
                f"dispatch would 404)"
            )
