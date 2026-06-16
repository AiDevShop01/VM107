"""Phase 87 Wave 4b — REQ-87-9 multi-indicator joint-pattern detection.

When ≥2 of the anchor indicators move in correlated direction within the
last 6 hours, the story-creation LLM prompt MUST be augmented with a
directive instructing it to name 2-3 of the correlated indicators in the
headline (e.g., "Mixed inflation signals with weakening labour market").

This skill is pure-data — no LLM call, no I/O. The macro_story_tracker
agent calls ``detect_joint_pattern`` once per tick on the polled release
batch, then concatenates ``joint_pattern_prompt_directive(pattern)`` into
the LLM prompt body.
"""
from __future__ import annotations

from collections import defaultdict

# Phase 87 RESEARCH §Wave 4 anchor set — the 5 indicators whose joint
# direction defines the "macro story" envelope. Kept narrow on purpose
# (REQ-87-9 says ≥2 of 3 anchors, RESEARCH expanded to 5 to cover the
# inflation / labour / growth / PMI / payrolls cluster).
ANCHOR_INDICATORS: set[str] = {
    "CPIAUCSL",  # inflation
    "UNRATE",    # labour
    "GDP",       # growth
    "NAPMPMI",   # PMI
    "PAYEMS",    # payrolls
}


def detect_joint_pattern(releases: list[dict]) -> dict:
    """Detect a multi-indicator joint pattern in a batch of recent releases.

    Args:
        releases: List of release dicts. Each MUST carry ``indicator_id``,
            ``release_date`` (ISO-8601 string), and ``surprise`` (float;
            sign drives direction). Releases for non-anchor indicators are
            ignored.

    Returns:
        Dict with three fields:
            * ``has_pattern`` (bool) — True iff ≥2 anchors share direction.
            * ``correlated_indicators`` (list[str]) — names of the
              correlated anchor indicators (≥2 entries if has_pattern).
            * ``direction`` (int) — +1 or -1 when has_pattern, else 0.

        Direction precedence is +1 first (favours bullish-surprise framing
        when both +1 and -1 groups have ≥2 entries; the LLM still sees the
        directive and can name either group).
    """
    by_indicator: dict[str, list[dict]] = defaultdict(list)
    for r in releases:
        if r.get("indicator_id") in ANCHOR_INDICATORS:
            by_indicator[r["indicator_id"]].append(r)

    # For each anchor, take the LATEST release's surprise sign as its direction.
    directions: dict[str, int] = {}
    for indicator, rows in by_indicator.items():
        latest = sorted(rows, key=lambda x: x.get("release_date", ""))[-1]
        s = latest.get("surprise", 0) or 0
        if s > 0:
            directions[indicator] = +1
        elif s < 0:
            directions[indicator] = -1
        else:
            directions[indicator] = 0

    # Look for ≥2 anchors moving same direction (+1 first, then -1).
    for sign in (+1, -1):
        group = sorted(k for k, v in directions.items() if v == sign)
        if len(group) >= 2:
            return {
                "has_pattern": True,
                "correlated_indicators": group,
                "direction": sign,
            }

    return {"has_pattern": False, "correlated_indicators": [], "direction": 0}


def joint_pattern_prompt_directive(pattern: dict) -> str:
    """Build the prompt directive that pushes the LLM to name the indicators.

    Returns an empty string when there is no joint pattern (the agent
    concatenates the result unconditionally, so empty-string means
    "no directive added").
    """
    if not pattern.get("has_pattern"):
        return ""
    names = ", ".join(pattern["correlated_indicators"])
    dir_word = "rising" if pattern["direction"] > 0 else "falling"
    return (
        "\n\nMULTI-INDICATOR PATTERN DETECTED (REQ-87-9): "
        f"{names} are all {dir_word}. The headline MUST name >=2 of these "
        "indicators (e.g., 'Mixed inflation signals with weakening "
        "labour market'). Use indicator names, not codes."
    )
