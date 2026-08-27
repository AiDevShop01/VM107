"""Phase 168 Plan 03 Task 1 — token budget + Contract §6 tier caps + L0->L4 ladder.

The tool-economy sub-contract (agent-catalogue/01 §6, Constitution 17 "minimum
sufficient state"): every agent-facing tool result is bounded by a token budget
so one poorly-behaved tool cannot flood the agent's context window. This module
is the single home for:

- the four Contract §6 tier caps (COMPACT<=250 / STANDARD<=750 / DETAILED<=2000 /
  RAW = explicit-only, no numeric cap);
- a deterministic ``estimate_tokens`` over a *scalar/struct* payload (never a
  series — the series stays server-side on VM102);
- ``effective_cap`` = min(tier cap, profile ``max_tool_result_tokens``) so a
  profile is authoritative and may only *tighten* the tier default;
- ``enforce_budget`` which returns a decision that marks ``outcome_class``
  "partial" (NEVER silently "success") when the payload would exceed the cap —
  a tool must degrade *visibly*;
- the L0->L4 progressive-disclosure ladder helpers (``next_detail_levels`` gives
  the strictly-wider levels; ``merge_detail_fields`` projects a per-tier field
  map into the cumulative payload for a requested level).

Pure module: pydantic + stdlib only, no VM102 / network / heavy deps — so it
imports host-clean and the budget tests run without the CI venv.
"""
from __future__ import annotations

import json
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# Detail tiers — Contract §6 (agent-catalogue/01 §6)
# ---------------------------------------------------------------------------

DetailTier = Literal["COMPACT", "STANDARD", "DETAILED", "RAW"]

# Per-tier hard token caps. RAW is explicit-request-only and carries NO numeric
# cap (a profile MAY still bound it via max_tool_result_tokens).
COMPACT: int = 250
STANDARD: int = 750
DETAILED: int = 2000
RAW: None = None

# Ordered COMPACT -> RAW; index == relative width. The L0->L4 disclosure ladder
# maps onto this ordering (L0 headline == COMPACT ... L4 raw == RAW).
DETAIL_TIERS: tuple[DetailTier, ...] = ("COMPACT", "STANDARD", "DETAILED", "RAW")

TIER_CAPS: dict[str, int | None] = {
    "COMPACT": COMPACT,
    "STANDARD": STANDARD,
    "DETAILED": DETAILED,
    "RAW": RAW,
}

# Characters-per-token heuristic (GPT-family ~4 chars/token). Deterministic and
# conservative — we only need a stable, monotonic estimate to enforce a cap, not
# an exact tokenizer (which would add a heavy dependency for no correctness gain).
_CHARS_PER_TOKEN: int = 4


# ---------------------------------------------------------------------------
# Ladder helpers
# ---------------------------------------------------------------------------


def tier_index(level: str) -> int:
    """Return the ordinal position of ``level`` in DETAIL_TIERS (0..3)."""
    try:
        return DETAIL_TIERS.index(level)  # type: ignore[arg-type]
    except ValueError as exc:
        raise ValueError(
            f"unknown detail level {level!r}; expected one of {DETAIL_TIERS}"
        ) from exc


def next_detail_levels(level: str) -> tuple[str, ...]:
    """The strictly-WIDER levels available from ``level`` (progressive disclosure).

    COMPACT -> (STANDARD, DETAILED, RAW); RAW -> (). Strictly-wider only: a level
    never lists itself or any narrower level, so a client can only escalate.
    """
    idx = tier_index(level)
    return DETAIL_TIERS[idx + 1 :]


def merge_detail_fields(
    fields_by_tier: dict[str, dict[str, Any]], level: str
) -> dict[str, Any]:
    """Cumulatively merge every tier's field map up to and including ``level``.

    ``fields_by_tier`` maps a tier -> the fields *introduced* at that tier. The
    result for a level is the union of all tiers at-or-below it, so a wider level
    is always a strict superset of a narrower one (monotonic disclosure). Tiers
    absent from the map contribute nothing.
    """
    cutoff = tier_index(level)
    merged: dict[str, Any] = {}
    for i in range(cutoff + 1):
        tier = DETAIL_TIERS[i]
        merged.update(fields_by_tier.get(tier, {}))
    return merged


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def _payload_to_text(payload: Any) -> str:
    """Serialise a scalar/struct payload to a deterministic string for estimation.

    Accepts a pydantic BaseModel (canonical JSON), a plain dict/list (json), or
    any scalar (str()). NEVER expects a series/DataFrame — the substrate keeps
    those server-side; a tool payload is a scalar or a small struct.
    """
    if isinstance(payload, BaseModel):
        return payload.model_dump_json()
    if isinstance(payload, (dict, list, tuple)):
        return json.dumps(payload, default=str, sort_keys=True)
    return str(payload)


def estimate_tokens(payload: Any) -> int:
    """Deterministic token estimate for a scalar/struct payload.

    ceil(len(serialised) / 4). Stable across calls (deterministic) and monotonic
    in payload size — the only two properties budget enforcement needs.
    """
    text = _payload_to_text(payload)
    return math.ceil(len(text) / _CHARS_PER_TOKEN)


# ---------------------------------------------------------------------------
# Cap resolution + enforcement
# ---------------------------------------------------------------------------


def effective_cap(tier: str, profile_cap: int | None) -> int | None:
    """Resolve the effective token cap = min(tier cap, profile max_tool_result_tokens).

    The profile is authoritative but may only *tighten*: it can lower a tier's
    default cap, never raise it. RAW has no tier cap (None) — a profile cap, if
    present, becomes the effective bound; otherwise it stays uncapped.
    """
    if tier not in TIER_CAPS:
        raise ValueError(f"unknown detail level {tier!r}; expected one of {DETAIL_TIERS}")
    tier_cap = TIER_CAPS[tier]
    if tier_cap is None and profile_cap is None:
        return None
    if tier_cap is None:
        return profile_cap
    if profile_cap is None:
        return tier_cap
    return min(tier_cap, profile_cap)


BudgetOutcome = Literal["success", "partial"]


class BudgetDecision(BaseModel):
    """The outcome of a budget check for one tool result (frozen).

    ``outcome_class`` is "partial" whenever ``truncated`` is True — the tool
    result exceeded its effective cap and MUST be surfaced as degraded, never
    silently returned as "success". The tool copies this onto the envelope's
    ``outcome_class`` and reduces its payload accordingly.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tier: DetailTier
    effective_cap: int | None
    estimated_tokens: int
    truncated: bool
    outcome_class: BudgetOutcome


def enforce_budget(
    payload: Any, tier: str, profile_cap: int | None = None
) -> BudgetDecision:
    """Check ``payload`` against the effective cap for ``tier`` (+ optional profile cap).

    Returns a :class:`BudgetDecision`. When the estimate exceeds the effective
    cap the decision is ``truncated=True`` / ``outcome_class="partial"`` — the
    contract is that a tool NEVER silently drops data to fit; it marks partial so
    the over-budget condition is visible to the agent (Constitution 17).
    """
    if tier not in TIER_CAPS:
        raise ValueError(f"unknown detail level {tier!r}; expected one of {DETAIL_TIERS}")
    cap = effective_cap(tier, profile_cap)
    estimated = estimate_tokens(payload)

    over = cap is not None and estimated > cap
    return BudgetDecision(
        tier=tier,  # type: ignore[arg-type]
        effective_cap=cap,
        estimated_tokens=estimated,
        truncated=over,
        outcome_class="partial" if over else "success",
    )
