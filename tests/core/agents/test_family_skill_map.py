"""Phase 48 Plan 06 — family_skill_map deterministic 1-of-5 dispatch.

CONTEXT § Decision 1: orchestrator loads exactly ONE family skill per Critic
invocation, deterministically resolved from StrategySpec.strategy_family.
No multi-skill loading in V1.

REQ-48-D1.
"""
from __future__ import annotations

import sys
from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest

from core.contracts.schemas import StrategyFamily


def test_family_skill_map_has_exactly_five_entries():
    """family_skill_map covers all 5 StrategyFamily enum members."""
    from core.agents.family_skill_map import family_skill_map

    assert len(family_skill_map) == 5
    assert set(family_skill_map.keys()) == set(StrategyFamily)


@pytest.mark.parametrize(
    "family,expected_skill_id",
    [
        (StrategyFamily.BREAKOUT, "breakout-critic"),
        (StrategyFamily.MEAN_REVERSION, "mean-reversion-critic"),
        (StrategyFamily.TREND_CONTINUATION, "trend-continuation-critic"),
        (StrategyFamily.AUCTION_ROTATION, "auction-rotation-critic"),
        (StrategyFamily.VOLATILITY_EXPANSION, "volatility-expansion-critic"),
    ],
)
def test_family_skill_map_deterministic_dispatch(family, expected_skill_id):
    """select_skill returns the locked skill_id for each family."""
    from core.agents.family_skill_map import select_skill

    assert select_skill(family) == expected_skill_id


def test_family_skill_map_values_are_unique():
    """No two families share a skill (1-of-5 dispatch, no overloading)."""
    from core.agents.family_skill_map import family_skill_map

    values = list(family_skill_map.values())
    assert len(values) == len(set(values))


def test_select_skill_unknown_family_raises_key_error():
    """Unknown family fails fast — no default fallback per CONTEXT § Decision 1."""
    from core.agents.family_skill_map import select_skill

    class _BogusFamily:
        pass

    with pytest.raises(KeyError):
        select_skill(_BogusFamily())  # type: ignore[arg-type]


def test_family_skill_map_values_match_skill_md_dir_names():
    """Each skill_id maps to an on-disk SKILL.md under the Critic profile."""
    from core.agents.family_skill_map import family_skill_map

    skills_root = (
        _VM107_ROOT / "agents" / "strategy_refinement_critic" / "skills"
    )
    for skill_id in family_skill_map.values():
        skill_md = skills_root / skill_id / "SKILL.md"
        assert skill_md.exists(), (
            f"Expected SKILL.md at {skill_md} for skill_id={skill_id}"
        )
