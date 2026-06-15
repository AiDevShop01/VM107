"""Wave 0 fixture-loadability smoke — Wave 2+ integration tests depend on these.

If any fixture artifact is malformed, this fails before later waves run their
integration tests. Wave 0 gate per VALIDATION § Wave 0 Requirements.
"""
import json
import pathlib

import pytest
import yaml

pytestmark = pytest.mark.phase_87

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"


def test_cpi_release_synthetic_loadable():
    data = json.loads((FIXTURES_DIR / "cpi_release_synthetic.json").read_text())
    for key in [
        "indicator_id",
        "release_id",
        "release_date",
        "actual",
        "forecast",
        "previous",
        "surprise",
        "surprise_pct",
        "event_status",
    ]:
        assert key in data, f"missing required Phase 83 econ_release key: {key}"
    assert data["event_status"] == "released"


def test_macro_graph_seed_minimal_loadable():
    data = yaml.safe_load((FIXTURES_DIR / "macro_graph_seed_test.yaml").read_text())
    assert len(data["indicators"]) == 3
    affects = sum(len(i.get("affects_chain", [])) for i in data["indicators"])
    drives = sum(len(i.get("drives", [])) for i in data["indicators"])
    assert affects >= 6, f"expected >=6 AFFECTS edges, got {affects}"
    assert drives >= 4, f"expected >=4 DRIVES edges, got {drives}"
    # Each AFFECTS edge has all 4 properties
    for ind in data["indicators"]:
        for edge in ind.get("affects_chain", []):
            for prop in ["strength", "confidence", "sample_size", "evidence_period"]:
                assert prop in edge, f"AFFECTS edge missing {prop}: {edge}"


def test_regime_history_2yr_loadable():
    data = json.loads((FIXTURES_DIR / "regime_history_2yr.json").read_text())
    assert data["seed"] == 87
    assert (
        len(data["anchor_releases"]) == 72
    ), "expected 24 months × 3 indicators = 72 releases"


def test_anchor_indicator_releases_loadable():
    data = json.loads((FIXTURES_DIR / "anchor_indicator_releases.json").read_text())
    assert len(data["anchor_combinations"]) == 7, (
        "expected 7 explicit combos (other 20 carry prior); LOCK-10 quant gate "
        "finalises the table before Wave 3 ships"
    )
