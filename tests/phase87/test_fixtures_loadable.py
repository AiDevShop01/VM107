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
    """LOCK-10 approval (Plan 87-05, 2026-06-15T23:25:07Z) finalised the
    threshold table as all 27 (3^3) anchor direction combinations explicitly
    enumerated. 7 of the 27 cells resolve to 'carry_prior' (echo prior
    regime); the other 20 name one of the 7 LOCK-2 regimes. Plan 87-01's
    original assertion (7 explicit + 20 implicit) is superseded by the
    Plan 87-05 fixture regeneration.
    """
    data = json.loads((FIXTURES_DIR / "anchor_indicator_releases.json").read_text())
    assert len(data["anchor_combinations"]) == 27, (
        "expected all 27 (3^3) anchor combinations explicitly enumerated "
        "per LOCK-10 approved table; Plan 87-05 regenerated the fixture"
    )
    # LOCK-10 partition: 6 carry_prior cells + 21 explicit-regime cells = 27.
    # (Stakeholder-approved 2026-06-15T23:25:07Z per 87-QUANT-APPROVAL.md.)
    carry_prior_cells = [
        c for c in data["anchor_combinations"]
        if c.get("expected_regime") == "carry_prior"
    ]
    explicit_cells = [
        c for c in data["anchor_combinations"]
        if c.get("expected_regime") != "carry_prior"
    ]
    assert len(carry_prior_cells) + len(explicit_cells) == 27, (
        f"partition mismatch: {len(carry_prior_cells)} carry_prior + "
        f"{len(explicit_cells)} explicit != 27"
    )
    assert len(carry_prior_cells) == 6, (
        f"LOCK-10 approved table has 6 carry_prior cells; "
        f"got {len(carry_prior_cells)}"
    )
    assert len(explicit_cells) == 21, (
        f"LOCK-10 approved table has 21 explicit-regime cells; "
        f"got {len(explicit_cells)}"
    )
    # Every explicit cell must name one of the 7 LOCK-2 regimes
    valid_regimes = {
        "expansion", "slowdown", "inflation", "disinflation",
        "stagflation", "recession", "recovery",
    }
    for cell in explicit_cells:
        assert cell["expected_regime"] in valid_regimes, (
            f"cell {cell!r} expected_regime is not a LOCK-2 regime"
        )
