"""Phase 48 Plan 06 — deterministic 1-of-5 family skill dispatcher.

CONTEXT § Decision 1: the strategy_refinement_critic uses one Agent Zero
profile plus per-family SKILL.md overlays (Phase 60 pattern). At Critic
invocation time the orchestrator resolves StrategySpec.strategy_family to
exactly ONE skill_id via this map and loads that overlay. NO multi-skill
loading in V1; NO default fallback. Unknown family fails fast with KeyError.

The skill_id values are the on-disk directory names at
    agents/strategy_refinement_critic/skills/<id>/SKILL.md
and the registry IDs at
    registry/skill/<id>.yaml

Phase 60 frontmatter validator (helpers/skills.py::_NAME_RE) requires
lowercase + digits + hyphens only; family ids use hyphens (not underscores).

Public API:
    family_skill_map  dict[StrategyFamily, str]
    select_skill(family) -> str   (KeyError on unknown family)
"""
from __future__ import annotations

from typing import Final

from core.contracts.schemas import StrategyFamily


family_skill_map: Final[dict[StrategyFamily, str]] = {
    StrategyFamily.BREAKOUT: "breakout-critic",
    StrategyFamily.MEAN_REVERSION: "mean-reversion-critic",
    StrategyFamily.TREND_CONTINUATION: "trend-continuation-critic",
    StrategyFamily.AUCTION_ROTATION: "auction-rotation-critic",
    StrategyFamily.VOLATILITY_EXPANSION: "volatility-expansion-critic",
}


def select_skill(family: StrategyFamily) -> str:
    """Return the deterministic skill_id for a StrategyFamily.

    Raises:
        KeyError: family is not one of the 5 locked StrategyFamily values.
                  No silent fallback — caller MUST handle unknown families
                  explicitly (CONTEXT § Decision 1 fail-fast discipline).
    """
    return family_skill_map[family]
