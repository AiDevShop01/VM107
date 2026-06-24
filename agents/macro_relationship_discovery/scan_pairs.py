"""Phase 89.2 — fixed scan pair list for nightly discovery.

VM102 correlation/lead-lag endpoints are indicator-vs-asset only (per
89.2-RESEARCH.md §Critical Design Note). Each tuple is
(FRED_indicator_code, asset_slug) where asset_slug ∈ {gold, eur, jpy, nasdaq}.

Candidate set covers Phase 86 known macro relationships (inflation/rates/yields
→ FX/metals/equities). Planner may extend as new pairs become tractable.
"""
from __future__ import annotations

# (FRED_code, asset_slug) — covers Phase 86 known relationships per RESEARCH.md
DEFAULT_SCAN_PAIRS: list[tuple[str, str]] = [
    ("CPIAUCSL", "gold"),
    ("CPIAUCSL", "eur"),
    ("CPIAUCSL", "jpy"),
    ("FEDFUNDS", "gold"),
    ("FEDFUNDS", "eur"),
    ("FEDFUNDS", "jpy"),
    ("FEDFUNDS", "nasdaq"),
    ("T10YIE", "gold"),
    ("UNRATE", "gold"),
    ("UNRATE", "nasdaq"),
    ("DGS10", "gold"),
    ("DGS10", "eur"),
]
