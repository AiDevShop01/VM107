"""Phase 87 Plan 06 (Wave 3) — deterministic 7-regime classifier.

Loads ``regime_threshold_table.json`` (LOCK-10 approved 27-entry table) at
module import. Any change to the table is a sibling decimal phase
(``87.1 — Regime Threshold Re-calibration``) with a fresh quant approval
signature + bumped ``regime_threshold_table_version`` — no silent edits.

Classifier is a pure dict lookup keyed on
``(cpi_dir, unrate_dir, gdp_dir)`` ∈ ``{-1, 0, 1}³``. Returns one of the
7 LOCK-2 regimes OR ``carry_prior`` — when carry_prior, the caller
(``MacroRegimeAnalyst.run``) reads the prior regime from the most recent
``macro_regime_classification`` row.

Wave 3 transition probability is deterministic (0.0/1.0). Plan 87-09
replaces ``transition_probability_v1`` with the BeliefStore Bayesian
posterior without changing the agent's call site.
"""
from __future__ import annotations

import json
import pathlib
from typing import Literal

Regime = Literal[
    "expansion",
    "slowdown",
    "inflation",
    "disinflation",
    "stagflation",
    "recession",
    "recovery",
]
Direction = Literal[-1, 0, 1]

_LOCK_2_REGIMES: frozenset[str] = frozenset(
    [
        "expansion",
        "slowdown",
        "inflation",
        "disinflation",
        "stagflation",
        "recession",
        "recovery",
    ]
)
_CARRY_PRIOR_TOKEN = "carry_prior"

_TABLE_PATH = pathlib.Path(__file__).parent / "regime_threshold_table.json"
if not _TABLE_PATH.exists():  # pragma: no cover — fail-fast at import
    raise RuntimeError(
        f"LOCK-10 regime_threshold_table.json missing at {_TABLE_PATH}. "
        "Plan 87-05 must complete (stakeholder approval) before Plan 87-06 "
        "(macro_regime_analyst) can ship."
    )


def _load_table() -> dict[tuple[int, int, int], str]:
    raw = json.loads(_TABLE_PATH.read_text())
    combos = raw.get("anchor_combinations", [])
    table: dict[tuple[int, int, int], str] = {}
    for entry in combos:
        key = (
            int(entry["cpi_dir"]),
            int(entry["unrate_dir"]),
            int(entry["gdp_dir"]),
        )
        decision = entry["expected_regime"]
        if decision != _CARRY_PRIOR_TOKEN and decision not in _LOCK_2_REGIMES:
            raise RuntimeError(
                f"regime_threshold_table.json has invalid expected_regime "
                f"{decision!r} for key {key} — must be one of the 7 LOCK-2 "
                f"regimes or 'carry_prior'"
            )
        table[key] = decision
    return table


_TABLE: dict[tuple[int, int, int], str] = _load_table()
TABLE_VERSION: str = json.loads(_TABLE_PATH.read_text()).get(
    "regime_threshold_table_version", "unknown"
)


def classify_regime(
    *,
    cpi_dir: Direction,
    unrate_dir: Direction,
    gdp_dir: Direction,
    prior_regime: Regime,
) -> tuple[Regime, bool]:
    """Map a 3-anchor direction tuple to one of 7 LOCK-2 regimes.

    Args:
        cpi_dir:    CPI direction (-1 falling, 0 flat, +1 rising).
        unrate_dir: Unemployment direction.
        gdp_dir:    GDP direction.
        prior_regime: Most-recent persisted regime — used to honour
            ``carry_prior`` entries in the LOCK-10 table.

    Returns:
        ``(regime, flipped)``:
          - regime: one of the 7 LOCK-2 regimes.
          - flipped: ``True`` iff the returned regime differs from
            ``prior_regime``. ``carry_prior`` cells always return
            ``(prior_regime, False)``.
    """
    decision = _TABLE.get((int(cpi_dir), int(unrate_dir), int(gdp_dir)))
    if decision is None or decision == _CARRY_PRIOR_TOKEN:
        return prior_regime, False
    return decision, decision != prior_regime


def transition_probability_v1(
    *,
    flipped: bool,
    decision_is_carry_prior: bool,
) -> float:
    """Wave 3 deterministic transition probability.

    Contract (per plan must_haves):
      - 0.0 if carry_prior (no flip signal) OR classifier returned the
        same regime.
      - 1.0 if hard flip to a different regime.
      - 0.5 reserved for the Wave 5 BeliefStore posterior (Plan 87-09)
        — never emitted by this v1 implementation.

    Plan 87-09 swaps this for the BeliefStore Bayesian posterior; the
    agent's call site does not change.
    """
    if decision_is_carry_prior:
        return 0.0
    return 1.0 if flipped else 0.0
