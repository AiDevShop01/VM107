"""Phase 47.3 — Hard reject predicate dispatch.

Each strategy YAML's ``hard_rejects[].name`` maps to a Python predicate
registered via ``@register_hard_reject``. Framework boot asserts every YAML
name has a registered predicate (OQ-7 / CF-5).

Predicates are defensive at runtime — exceptions inside a predicate are
logged + skipped; a predicate bug must NOT veto an otherwise valid evaluation.

CF-3 — predicates that depend on category data MUST conservatively return
True when the underlying data is ``not_available`` (safety bias). Plan 05
ships the actual predicates; this module just supplies the registry +
dispatch + boot-time assertion plumbing.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from fingpt_core.contracts.agents.pre_trade_evaluation import CategoryResult

    from .context import EvaluationContext

log = logging.getLogger(__name__)

# (strategy_id, hard_reject_name) -> predicate(ctx, by_name) -> bool
_HARD_REJECTS: dict[tuple[str, str], Callable] = {}


def register_hard_reject(strategy_id: str, name: str):
    """Decorator: register a hard-reject predicate for ``(strategy_id, name)``.

    Predicate signature: ``(ctx, by_name) -> bool`` where ``by_name`` is a
    ``dict[str, CategoryResult]`` keyed by category name.

    Raises ``RuntimeError`` on duplicate registration.
    """

    def _decorator(fn: Callable):
        key = (strategy_id, name)
        if key in _HARD_REJECTS:
            raise RuntimeError(
                f"Phase 47.3 invariant: duplicate hard_reject predicate for {key}"
            )
        _HARD_REJECTS[key] = fn
        return fn

    return _decorator


def is_hard_reject_registered(strategy_id: str, name: str) -> bool:
    """True if ``(strategy_id, name)`` has a registered predicate."""
    return (strategy_id, name) in _HARD_REJECTS


def detect_hard_rejects(
    ctx: "EvaluationContext",
    results: "list[CategoryResult]",
) -> list[str]:
    """Iterate ``ctx.strategy.hard_rejects``, dispatch each predicate, collect hits.

    Returns the list of ``hard_reject.name`` values whose predicate returned
    True. Defensive: a predicate exception ≠ veto — logged and skipped.

    If ``ctx.strategy`` is None, returns ``[]`` (no strategy → no veto).
    """
    if not ctx.strategy:
        return []
    by_name = {r.name: r for r in results}
    hits: list[str] = []
    strategy_id = ctx.strategy_id or ctx.strategy.id
    for hr in ctx.strategy.hard_rejects:
        predicate = _HARD_REJECTS.get((strategy_id, hr.name))
        if predicate is None:
            # Boot-time assertion should have caught this; defensive at runtime.
            log.warning(
                "Phase 47.3: hard_reject predicate missing for (%s, %s) — skipping.",
                strategy_id,
                hr.name,
            )
            continue
        try:
            if predicate(ctx, by_name):
                hits.append(hr.name)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Phase 47.3: hard_reject predicate raised for (%s, %s): %s — skipping.",
                strategy_id,
                hr.name,
                exc,
            )
            continue
    return hits
