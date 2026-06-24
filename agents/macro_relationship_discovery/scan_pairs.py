"""Phase 89.2 — fixed scan pair list for nightly discovery.

VM102 correlation/lead-lag endpoints are indicator-vs-asset only (per
89.2-RESEARCH.md §Critical Design Note). Each tuple is
(FRED_indicator_code, asset_slug) where asset_slug ∈ {gold, eur, jpy, nasdaq}.

Candidate set covers Phase 86 known macro relationships (inflation/rates/yields
→ FX/metals/equities). Planner may extend as new pairs become tractable.

NOTE: every indicator_code here MUST exist in VM102's ref_economic_indicators
catalog. Adding an unrecognized code yields a 400 UnknownIndicator from VM102's
macro_analytics router and the pair is silently skipped (per-candidate
exception swallowing in agent.py), but the noise pollutes logs and falsely
deflates throughput. Verify with:

    SELECT indicator_code FROM ref_economic_indicators
    WHERE indicator_code = '<NEW_CODE>';

before adding a new pair. Discovered during Phase 89.2-07 smoke (T10YIE was
absent — only T10Y2Y and T10Y3M exist for the 10Y-Treasury family).
"""
from __future__ import annotations

# (FRED_code, asset_slug) — covers Phase 86 known relationships per RESEARCH.md.
# T10Y2Y (10Y - 2Y yield curve slope) substitutes for T10YIE (10Y breakeven
# inflation) — T10YIE is not in the VM102 catalog as of Phase 89.2-07 smoke;
# T10Y2Y carries a closely related rate/inflation-expectation signal (yield
# curve inversion is the canonical leading indicator of growth + rate-cut
# expectations affecting gold).
DEFAULT_SCAN_PAIRS: list[tuple[str, str]] = [
    ("CPIAUCSL", "gold"),
    ("CPIAUCSL", "eur"),
    ("CPIAUCSL", "jpy"),
    ("FEDFUNDS", "gold"),
    ("FEDFUNDS", "eur"),
    ("FEDFUNDS", "jpy"),
    ("FEDFUNDS", "nasdaq"),
    ("T10Y2Y", "gold"),
    ("UNRATE", "gold"),
    ("UNRATE", "nasdaq"),
    ("DGS10", "gold"),
    ("DGS10", "eur"),
]
