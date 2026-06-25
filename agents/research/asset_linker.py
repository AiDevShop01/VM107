"""Phase 92 Plan 03 — Deterministic asset linker.

Joins ``doc.indicators ∩ asset_universe.yaml drivers_via_indicators`` to
produce ``doc.assets``. The mapping is hand-curated by the macro team in
``VM107/data/asset_universe.yaml`` — this module is just the join logic.

Public API:

    link_assets(indicator_ids: list[str]) -> list[dict]

Returns a list of {asset_id, via_indicator, confidence, direction} entries.
Duplicates (the same asset linked via multiple indicators) are aggregated
to MAX confidence, keeping the via_indicator that produced that max.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


_VM107_ROOT = Path(__file__).resolve().parents[2]
_ASSET_UNIVERSE_PATH = _VM107_ROOT / "data" / "asset_universe.yaml"

# Cached on first use; (asset_id, indicator_id) → (confidence, direction)
_universe_cache: dict[str, list[dict[str, Any]]] | None = None


def _load_universe() -> dict[str, list[dict[str, Any]]]:
    """Load asset_universe.yaml into ``{asset_id: [driver_dict, ...]}`` form."""
    global _universe_cache
    if _universe_cache is not None:
        return _universe_cache

    raw = yaml.safe_load(_ASSET_UNIVERSE_PATH.read_text())
    out: dict[str, list[dict[str, Any]]] = {}
    for asset in raw.get("assets", []):
        out[asset["id"]] = list(asset.get("drivers_via_indicators", []))
    _universe_cache = out
    return out


def link_assets(indicator_ids: list[str]) -> list[dict[str, Any]]:
    """Return assets driven by any of the given indicator IDs.

    Args:
        indicator_ids: List of FRED IDs (e.g. ['CPIAUCSL', 'DGS10']).

    Returns:
        List of dicts {asset_id, via_indicator, confidence, direction}.
        Duplicates are aggregated to max-confidence — if an asset is
        driven by multiple indicators in the input, only one entry is
        returned, carrying the via_indicator + direction of the
        highest-confidence driver.
    """
    if not indicator_ids:
        return []

    universe = _load_universe()
    indicator_set = set(indicator_ids)

    # asset_id → best driver dict so far (max confidence)
    best: dict[str, dict[str, Any]] = {}
    for asset_id, drivers in universe.items():
        for driver in drivers:
            iid = driver.get("indicator_id")
            if iid not in indicator_set:
                continue
            conf = float(driver.get("confidence", 0.0))
            direction = driver.get("direction", "mixed")
            candidate = {
                "asset_id": asset_id,
                "via_indicator": iid,
                "confidence": conf,
                "direction": direction,
            }
            if asset_id not in best or conf > best[asset_id]["confidence"]:
                best[asset_id] = candidate

    # Order by descending confidence then asset_id for determinism
    return sorted(
        best.values(),
        key=lambda a: (-a["confidence"], a["asset_id"]),
    )


__all__ = ["link_assets"]
