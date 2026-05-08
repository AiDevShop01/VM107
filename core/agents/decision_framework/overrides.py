"""Phase 47.3 — Strategy override registry.

Module-level dict keyed by ``(strategy_id, category_name) → callable``. Strategy
modules at ``decision_framework/strategies/<id>.py`` register their overrides
via ``@register_override``; framework reads at evaluation time.

OQ-3: module-level dict (not per-instance) for simplicity.
OQ-6: decorator pattern per CONTEXT skeleton.

Risk 8 lock: ``weight_multiplier`` is clamped to ``<= 1.0`` — V1 prohibits
weight inflation so the running ``max_score`` cannot drift above 100.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from .context import EvaluationContext

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CategoryWeight:
    """Returned by an override callable.

    ``weight_multiplier`` is clamped to <= 1.0 by ``safe_resolve_weight``
    (Risk 8 lock — V1 prohibits weight inflation).
    """

    weight_multiplier: float = 1.0
    threshold_strong: Optional[float] = None
    threshold_weak: Optional[float] = None
    note: Optional[str] = None


# Module-level registry (OQ-3)
_OVERRIDES: dict[tuple[str, str], Callable] = {}


def register_override(strategy_id: str, category_name: str):
    """Decorator: register an override for ``(strategy_id, category_name)``.

    Raises ``RuntimeError`` on duplicate registration — duplicates indicate a
    programming error (two modules trying to own the same slot).
    """

    def _decorator(fn: Callable):
        key = (strategy_id, category_name)
        if key in _OVERRIDES:
            raise RuntimeError(
                f"Phase 47.3 invariant: duplicate override registration for {key}"
            )
        _OVERRIDES[key] = fn
        return fn

    return _decorator


def resolve_override(
    strategy_id: str, category_name: str
) -> Optional[Callable]:
    """Return the override callable for ``(strategy_id, category_name)``,
    or None if no override is registered."""
    return _OVERRIDES.get((strategy_id, category_name))


def safe_resolve_weight(
    strategy_id: Optional[str],
    category_name: str,
    ctx: "EvaluationContext",
    default_max_points: int,
) -> tuple[int, Optional[str]]:
    """Plan 04 helper. Returns ``(max_points_after_override, note)``.

    Wraps ``resolve_override`` with safe-call:
    - No strategy → return defaults unchanged.
    - No override registered → return defaults unchanged.
    - Override raises → log + return defaults with explanatory note.
    - Override returns ``weight_multiplier > 1.0`` → reject (Risk 8 lock) and
      return defaults with explanatory note.

    Otherwise returns ``round(default_max_points * weight_multiplier)`` with
    the override's ``note`` propagated for ``CategoryResult.override_applied``.
    """
    if not strategy_id:
        return default_max_points, None
    fn = resolve_override(strategy_id, category_name)
    if fn is None:
        return default_max_points, None
    try:
        spec = fn(ctx)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Phase 47.3 override callable raised for (%s, %s): %s — falling back to defaults.",
            strategy_id,
            category_name,
            exc,
        )
        return default_max_points, f"override_failed: {type(exc).__name__}"
    if not isinstance(spec, CategoryWeight):
        log.warning(
            "Phase 47.3 override for (%s, %s) returned %s, expected CategoryWeight — ignoring.",
            strategy_id,
            category_name,
            type(spec).__name__,
        )
        return default_max_points, "override_rejected: bad_return_type"
    if spec.weight_multiplier > 1.0:
        # Risk 8 lock — V1 prohibits weight inflation.
        return default_max_points, "override_rejected: weight_multiplier > 1.0"
    new_max = round(default_max_points * spec.weight_multiplier)
    return new_max, spec.note
