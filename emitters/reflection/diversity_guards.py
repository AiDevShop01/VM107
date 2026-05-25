"""Diversity guards — Phase 67 Plan 07 (REQ-67-4).

Enforces the CONTEXT.md §4 diversity rules over a score-sorted candidate list:

    Default rules:
        max 2 prompts per same category
        max 1 prompt per same intervention_type
        max 1 prompt per same originating_pattern

    Dominant-session-theme override (one domain genuinely dominates):
        max 3 prompts per same category
        max 2 prompts per same intervention_type
        (originating_pattern cap unchanged at 1)

The guard returns (selected, rejected_by_diversity) tuple. Each rejected
candidate carries a non-empty ``rejected_by_diversity_guard`` reason so
Phase 62 tuning can backtrack which guard fired.

Guard semantics: highest-score wins each slot — input is assumed
descending-sorted by score, but the function defensively re-sorts to
ensure determinism regardless of caller order.
"""
from __future__ import annotations

from typing import Any


def apply_diversity_guards(
    candidates: list[Any],
    dominant_theme: str | None = None,
) -> tuple[list[Any], list[Any]]:
    """Apply diversity guards to candidates, returning (selected, rejected).

    Args:
        candidates: list of candidate objects with attributes:
            score, category, intervention_type, originating_pattern.
            Must also have a writable ``rejected_by_diversity_guard``
            string attribute and a writable ``selected`` bool attribute.
        dominant_theme: optional category name. When set, the per-category
            cap is loosened from 2 to 3 and the per-intervention_type cap
            from 1 to 2 (CONTEXT.md §4 override).

    Returns:
        (selected, rejected) — two lists, each candidate appears in
        exactly one of them. selected may be < 4; the synthesizer's
        coherence pass may further reduce it.
    """
    max_per_category = 3 if dominant_theme else 2
    max_per_intervention = 2 if dominant_theme else 1
    # originating_pattern cap stays at 1 regardless of theme
    max_per_pattern = 1

    # Defensive descending sort so guard fires deterministically on score.
    sorted_candidates = sorted(
        candidates,
        key=lambda c: (-getattr(c, "score", 0.0), getattr(c, "candidate_id", "")),
    )

    selected: list[Any] = []
    rejected: list[Any] = []

    cat_count: dict[str, int] = {}
    intv_count: dict[str, int] = {}
    pat_count: dict[str, int] = {}

    for c in sorted_candidates:
        category = getattr(c, "category", "")
        intervention = getattr(c, "intervention_type", "")
        pattern = getattr(c, "originating_pattern", "")

        # Check each guard in priority order — first violation wins as the
        # rejected_by_diversity_guard reason.
        if cat_count.get(category, 0) >= max_per_category:
            c.rejected_by_diversity_guard = (
                f"max_per_category({max_per_category}) exceeded for {category}"
            )
            c.selected = False
            rejected.append(c)
            continue

        if intv_count.get(intervention, 0) >= max_per_intervention:
            c.rejected_by_diversity_guard = (
                f"max_per_intervention({max_per_intervention}) exceeded "
                f"for {intervention}"
            )
            c.selected = False
            rejected.append(c)
            continue

        # Pattern slot only checked when a non-empty originating_pattern is set
        if pattern and pat_count.get(pattern, 0) >= max_per_pattern:
            c.rejected_by_diversity_guard = (
                f"max_per_originating_pattern({max_per_pattern}) exceeded "
                f"for {pattern}"
            )
            c.selected = False
            rejected.append(c)
            continue

        # Accept
        c.selected = True
        c.rejected_by_diversity_guard = None
        selected.append(c)
        cat_count[category] = cat_count.get(category, 0) + 1
        intv_count[intervention] = intv_count.get(intervention, 0) + 1
        if pattern:
            pat_count[pattern] = pat_count.get(pattern, 0) + 1

    return selected, rejected
