"""Phase 92 Plan 03 — asset_linker tests.

Plan-quote: "test_asset_linker_yaml.py: doc.indicators=['CPIAUCSL'] →
expected assets includes 'GOLD' AND 'UST10Y' AND 'DXY' (per asset_universe.yaml
seed)".

The asset_linker deterministically joins doc.indicators ∩
asset_universe.yaml drivers_via_indicators. For each indicator in the input,
it finds assets that list the indicator as a driver and returns
{asset_id, via_indicator, confidence, direction}. Duplicates aggregate to
max-confidence.
"""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.phase92


def test_cpiaucsl_links_to_gold_ust10y_dxy():
    from agents.research.asset_linker import link_assets

    result = link_assets(["CPIAUCSL"])
    ids = {a["asset_id"] for a in result}
    assert "GOLD" in ids, f"CPIAUCSL must link to GOLD; got {ids}"
    assert "UST10Y" in ids, f"CPIAUCSL must link to UST10Y; got {ids}"
    assert "DXY" in ids, f"CPIAUCSL must link to DXY; got {ids}"


def test_empty_indicators_returns_empty_list():
    from agents.research.asset_linker import link_assets

    assert link_assets([]) == []


def test_unknown_indicator_returns_empty_list():
    from agents.research.asset_linker import link_assets

    assert link_assets(["BOGUS_INDICATOR_ID_XYZ"]) == []


def test_asset_link_carries_direction_and_confidence():
    from agents.research.asset_linker import link_assets

    result = link_assets(["DTWEXBGS"])  # broad dollar
    dxy = next((a for a in result if a["asset_id"] == "DXY"), None)
    assert dxy is not None, "DTWEXBGS must link to DXY"
    assert dxy["direction"] == "positive"
    assert dxy["confidence"] >= 0.9, f"DTWEXBGS→DXY confidence should be high; got {dxy['confidence']}"
    assert dxy["via_indicator"] == "DTWEXBGS"


def test_duplicate_asset_via_multiple_indicators_keeps_max_confidence():
    """SP500 sits in QQQ via SP500 (conf=0.95) AND via DGS10 (conf=0.65, negative).
    Linking [SP500, DGS10] should return ONE QQQ entry with confidence 0.95.
    """
    from agents.research.asset_linker import link_assets

    result = link_assets(["SP500", "DGS10"])
    qqq_entries = [a for a in result if a["asset_id"] == "QQQ"]
    assert len(qqq_entries) == 1, f"Expected ONE QQQ entry; got {qqq_entries}"
    assert qqq_entries[0]["confidence"] == 0.95


def test_assets_returned_are_uppercase_ids():
    from agents.research.asset_linker import link_assets

    result = link_assets(["DGS10"])
    for a in result:
        assert a["asset_id"].isupper() or "_" in a["asset_id"], (
            f"Asset IDs should be uppercase / underscored; got {a['asset_id']!r}"
        )
