"""Coherence pass — Phase 67 Plan 07 (REQ-67-4).

Operates on the 4-prompt SET (post-diversity) and enforces:

  * No contradictions — e.g. "too aggressive" + "too passive" in the
    same set produces a low coherence_score and triggers a swap when a
    suitable alternative is available in the candidate pool.
  * emotional_load budget — sum across 4 prompts ≤ 2.5; if exceeded,
    swap the highest-load prompt for the next-highest-score
    non-conflicting candidate.
  * Temporal mix — at least 1 immediate-session + at least 1
    longitudinal prompt; if missing, swap in a candidate matching the
    underrepresented scale.
  * reflection_set_coherence_score — final scalar in [0.0, 1.0].

Each remediation step reduces the coherence score by a penalty so a
"reluctantly fixed" set scores below a "naturally clean" set, and an
unfixable set (no pool alternative) carries the lowest score.
"""
from __future__ import annotations

from typing import Any


# Locked contradiction pairs (CONTEXT.md §4 + planner discretion examples).
CONTRADICTION_PAIRS: list[tuple[str, str]] = [
    ("too_aggressive", "too_passive"),
    ("overtrading", "undertrading"),
    ("premature_entry", "delayed_entry"),
    ("too_tight_stop", "too_wide_stop"),
    ("oversize", "undersize"),
]


EMOTIONAL_LOAD_BUDGET = 2.5


def _candidate_flags(c: Any) -> set[str]:
    return set(getattr(c, "flags", ()) or ())


def _has_contradiction(selected: list[Any]) -> tuple[str, str] | None:
    """Return the first contradiction pair found, or None."""
    flag_set: set[str] = set()
    for c in selected:
        flag_set.update(_candidate_flags(c))
    for a, b in CONTRADICTION_PAIRS:
        if a in flag_set and b in flag_set:
            return (a, b)
    return None


def _find_offender(selected: list[Any], flag: str) -> Any | None:
    """Locate the LOWEST-score candidate carrying the offending flag."""
    candidates_with_flag = [c for c in selected if flag in _candidate_flags(c)]
    if not candidates_with_flag:
        return None
    return min(
        candidates_with_flag, key=lambda c: getattr(c, "score", 0.0)
    )


def _find_swap_for_contradiction(
    pool: list[Any],
    excluded_ids: set[str],
    offending_flag: str,
) -> Any | None:
    """Find a pool candidate that does NOT carry the offending flag."""
    for candidate in sorted(
        pool, key=lambda c: -getattr(c, "score", 0.0)
    ):
        cid = getattr(candidate, "candidate_id", id(candidate))
        if cid in excluded_ids:
            continue
        if offending_flag in _candidate_flags(candidate):
            continue
        return candidate
    return None


def _find_swap_for_load(
    pool: list[Any], excluded_ids: set[str], max_load: float
) -> Any | None:
    """Find a pool candidate with emotional_load <= max_load."""
    for candidate in sorted(
        pool, key=lambda c: -getattr(c, "score", 0.0)
    ):
        cid = getattr(candidate, "candidate_id", id(candidate))
        if cid in excluded_ids:
            continue
        if getattr(candidate, "emotional_load", 0.0) <= max_load:
            return candidate
    return None


def _find_swap_for_temporal(
    pool: list[Any], excluded_ids: set[str], wanted_scale: str
) -> Any | None:
    """Find a pool candidate matching the missing temporal scale."""
    for candidate in sorted(
        pool, key=lambda c: -getattr(c, "score", 0.0)
    ):
        cid = getattr(candidate, "candidate_id", id(candidate))
        if cid in excluded_ids:
            continue
        if getattr(candidate, "temporal_scale", "") == wanted_scale:
            return candidate
    return None


def coherence_check(
    selected: list[Any], all_candidates: list[Any]
) -> tuple[list[Any], float]:
    """Run the coherence pass — may swap candidates, returns (final, score).

    Args:
        selected: post-diversity selected candidates (typically ≤ 4).
        all_candidates: full candidate pool, used as swap source.

    Returns:
        (final, coherence_score) — final is the (possibly remediated)
        prompt set; coherence_score is in [0.0, 1.0] reflecting how many
        violations remain + how invasive the remediation was.
    """
    final = list(selected)
    selected_ids = {getattr(c, "candidate_id", id(c)) for c in final}
    score = 1.0

    # ── 1. Contradiction detection + swap ──────────────────────────────
    contradiction = _has_contradiction(final)
    if contradiction:
        # Swap the lower-score offender first; keep the higher-score one.
        a, b = contradiction
        off_a = _find_offender(final, a)
        off_b = _find_offender(final, b)
        # The "lowest-score offender" overall is the one to drop.
        if off_a and off_b:
            offender = (
                off_a
                if getattr(off_a, "score", 0.0) <= getattr(off_b, "score", 0.0)
                else off_b
            )
            offending_flag = a if offender is off_a else b
        else:
            offender = off_a or off_b
            offending_flag = a if offender is off_a else b

        if offender is not None:
            swap_candidate = _find_swap_for_contradiction(
                all_candidates, selected_ids, offending_flag
            )
            if swap_candidate is not None:
                # Mark offender rejected + remove + add swap
                offender.selected = False
                offender.rejection_reason = (
                    f"coherence_contradiction_with_{offending_flag}"
                )
                offender_id = getattr(offender, "candidate_id", id(offender))
                final = [
                    c
                    for c in final
                    if getattr(c, "candidate_id", id(c)) != offender_id
                ]
                selected_ids.discard(offender_id)
                swap_id = getattr(
                    swap_candidate, "candidate_id", id(swap_candidate)
                )
                final.append(swap_candidate)
                selected_ids.add(swap_id)
                # Remediation penalty
                score -= 0.15
            else:
                # Couldn't fix — bigger penalty
                score -= 0.30

    # ── 2. Emotional load budget ──────────────────────────────────────
    total_load = sum(
        float(getattr(c, "emotional_load", 0.0) or 0.0) for c in final
    )
    while total_load > EMOTIONAL_LOAD_BUDGET and final:
        # Swap the highest-load prompt for a calmer alternative
        hottest = max(
            final, key=lambda c: getattr(c, "emotional_load", 0.0)
        )
        slack = EMOTIONAL_LOAD_BUDGET - (
            total_load - float(getattr(hottest, "emotional_load", 0.0))
        )
        swap_candidate = _find_swap_for_load(
            all_candidates, selected_ids, max_load=max(slack, 0.0)
        )
        if swap_candidate is None:
            score -= 0.20
            break

        hottest.selected = False
        hottest.rejection_reason = "coherence_emotional_load_overflow"
        hottest_id = getattr(hottest, "candidate_id", id(hottest))
        final = [
            c
            for c in final
            if getattr(c, "candidate_id", id(c)) != hottest_id
        ]
        selected_ids.discard(hottest_id)
        swap_id = getattr(swap_candidate, "candidate_id", id(swap_candidate))
        final.append(swap_candidate)
        selected_ids.add(swap_id)
        score -= 0.10
        total_load = sum(
            float(getattr(c, "emotional_load", 0.0) or 0.0) for c in final
        )

    # ── 3. Temporal mix ───────────────────────────────────────────────
    if final:
        scales = {getattr(c, "temporal_scale", "") for c in final}
        if (
            "immediate-session" not in scales
            or "longitudinal" not in scales
        ):
            wanted = (
                "longitudinal"
                if "longitudinal" not in scales
                else "immediate-session"
            )
            swap_candidate = _find_swap_for_temporal(
                all_candidates, selected_ids, wanted
            )
            if swap_candidate is not None:
                # Drop the lowest-score selected candidate from the
                # OPPOSITE scale to make room.
                opposite = (
                    "immediate-session"
                    if wanted == "longitudinal"
                    else "longitudinal"
                )
                victims = [
                    c
                    for c in final
                    if getattr(c, "temporal_scale", "") == opposite
                ]
                if victims:
                    drop = min(
                        victims, key=lambda c: getattr(c, "score", 0.0)
                    )
                    drop.selected = False
                    drop.rejection_reason = "coherence_temporal_mix"
                    drop_id = getattr(drop, "candidate_id", id(drop))
                    final = [
                        c
                        for c in final
                        if getattr(c, "candidate_id", id(c)) != drop_id
                    ]
                    selected_ids.discard(drop_id)
                    swap_id = getattr(
                        swap_candidate, "candidate_id", id(swap_candidate)
                    )
                    final.append(swap_candidate)
                    selected_ids.add(swap_id)
                    score -= 0.10
            else:
                # No swap available, signal coherence drop
                score -= 0.20

    score = max(0.0, min(1.0, score))
    return final, score
