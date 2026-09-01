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
#
# 137-07 OPERATOR DECISION (B-01, D-08 RETARGET): D-08 originally proposed `status: planned`.
# `planned` is NOT a valid CapabilityStatus enum member — the enum is exactly
# {STUB, EXPERIMENTAL, REAL, DEPRECATED} (fingpt_core/contracts/capability_registry/enums.py),
# and `status` is a required validated field, so `planned` would fail boot validation. The
# confirmed-skeleton semantics ("excluded from the REAL dispatch set", index.py:44 filters
# `status != REAL`) are ALREADY satisfied by the existing `status: stub`. So the confirmed
# skeleton is asserted against the real, valid enum value `stub` — NOT `planned`. No yaml
# status flip is performed: vm107.macro_surprise_forecaster is already `status: stub`.
SKELETON_SET_CONFIRMED = True
# Confirmed skeleton ids — genuinely module-less / dispatch-unreachable and already
# non-REAL (status: stub, so excluded from the REAL set at index.py:44).
# P173 (D-03): vm107.macro_surprise_forecaster was the last remaining candidate and has
# been RETIRED (deprecate-in-place: registry status: deprecated + agent_contract.status:
# retired). It is no longer a skeleton, so the candidate list is now empty — the terminal
# zero-skeleton state for this suite.
SKELETON_CANDIDATES: tuple[str, ...] = ()
# Accepted confirmed-skeleton status: a confirmed skeleton is one whose status is non-REAL.
# D-08's `planned` retargeted to the existing valid enum value `stub` per operator decision
# (no enum change, reconciliation scope).
CONFIRMED_SKELETON_STATUSES: frozenset[str] = frozenset({"stub"})


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


def test_confirmed_skeletons_are_non_real_stub():
    """Each confirmed skeleton profile carries a non-REAL status (D-08 retargeted to `stub`).

    D-08 originally said `status: planned`, but `planned` is not a valid CapabilityStatus
    enum member ({STUB, EXPERIMENTAL, REAL, DEPRECATED}). The confirmed-skeleton semantics —
    excluded from the REAL dispatch set (index.py:44 filters `status != REAL`) — are already
    satisfied by the existing `status: stub`. Assert against the real, valid enum value.
    """
    if not SKELETON_SET_CONFIRMED:
        pytest.skip("skeleton set pending 137-07 confirmation")
    if not SKELETON_CANDIDATES:
        # P173 (D-03): the last confirmed skeleton (macro_surprise_forecaster) was RETIRED —
        # an empty candidate list is now the valid terminal zero-skeleton state.
        pytest.skip("no confirmed skeletons remain — all retired (P173 D-03)")
    for profile_id in SKELETON_CANDIDATES:
        status = _profile_status(profile_id)
        assert status is not None, f"skeleton candidate {profile_id!r} has no profile yaml"
        assert status in CONFIRMED_SKELETON_STATUSES, (
            f"{profile_id}: confirmed skeleton must carry a non-REAL status "
            f"{set(CONFIRMED_SKELETON_STATUSES)!r} (D-08 `planned` retargeted to valid enum "
            f"`stub`), got {status!r}"
        )
        assert status != "real", (
            f"{profile_id}: a confirmed skeleton must not be REAL (would enter dispatch set)"
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
