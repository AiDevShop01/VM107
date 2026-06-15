"""Phase 87 Plan 06 (Wave 3) — classifier rule-table parametrised test.

Asserts the deterministic 27-entry classifier returns the LOCK-10-approved
``expected_regime`` for every anchor combo in
``fixtures/anchor_indicator_releases.json``. ``carry_prior`` rows must
echo the supplied ``prior_regime``.

VALIDATION row 87-03-01 + REQ-87-3 acceptance — classifier rules.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agents.macro_regime_analyst.skill_regime_classifier import (
    TABLE_VERSION,
    classify_regime,
)

pytestmark = pytest.mark.phase_87


FIXTURE_PATH = (
    pathlib.Path(__file__).parent / "fixtures" / "anchor_indicator_releases.json"
)
_FIXTURE = json.loads(FIXTURE_PATH.read_text())
COMBOS: list[dict] = _FIXTURE["anchor_combinations"]
FIXTURE_TABLE_VERSION: str = _FIXTURE["regime_threshold_table_version"]


def _id(combo: dict) -> str:
    return (
        f"cpi{combo['cpi_dir']:+d}_"
        f"unrate{combo['unrate_dir']:+d}_"
        f"gdp{combo['gdp_dir']:+d}->"
        f"{combo['expected_regime']}"
    )


def test_table_version_matches_fixture():
    """Runtime table_version and test fixture must be byte-identical sources.

    Plan 87-05 ships ``regime_threshold_table.json`` to both
    ``VM107/agents/macro_regime_analyst/`` (runtime) and
    ``VM107/tests/phase87/fixtures/`` (test). The two MUST stay in lock-
    step — drift would silently let classifier rules diverge from the
    audited table.
    """
    assert TABLE_VERSION == FIXTURE_TABLE_VERSION, (
        f"runtime regime_threshold_table_version={TABLE_VERSION!r} != "
        f"fixture regime_threshold_table_version={FIXTURE_TABLE_VERSION!r}. "
        "Plan 87-05 ships them as byte-identical mirrors — investigate drift."
    )


def test_fixture_has_27_combos():
    """LOCK-10 approved table has all 27 (3^3) anchor combinations."""
    assert len(COMBOS) == 27, (
        f"Expected 27 anchor combinations (3 dirs ^ 3 anchors), "
        f"got {len(COMBOS)}. Audit fixtures/anchor_indicator_releases.json."
    )


@pytest.mark.parametrize("combo", COMBOS, ids=_id)
def test_classifier_returns_expected_regime(combo: dict):
    """Every LOCK-10 anchor combo returns its ``expected_regime``.

    ``carry_prior`` cells must echo the ``prior_regime`` we supply (any
    of the 7 regimes — we use 'expansion' here for determinism).
    """
    prior = "expansion"
    regime, flipped = classify_regime(
        cpi_dir=combo["cpi_dir"],
        unrate_dir=combo["unrate_dir"],
        gdp_dir=combo["gdp_dir"],
        prior_regime=prior,
    )
    if combo["expected_regime"] == "carry_prior":
        assert regime == prior, (
            f"carry_prior cell {combo!r} must echo prior_regime={prior!r}; "
            f"got {regime!r}"
        )
        assert flipped is False, (
            f"carry_prior cell {combo!r} must NOT flip; got flipped={flipped}"
        )
    else:
        assert regime == combo["expected_regime"], (
            f"combo {combo!r} expected {combo['expected_regime']!r}; "
            f"got {regime!r}"
        )


def test_classifier_flipped_flag_for_known_stagflation_flip():
    """When prior=expansion and combo→stagflation, flipped MUST be True."""
    regime, flipped = classify_regime(
        cpi_dir=1, unrate_dir=1, gdp_dir=-1, prior_regime="expansion",
    )
    assert regime == "stagflation"
    assert flipped is True


def test_classifier_flipped_false_when_same_regime():
    """When prior=stagflation and combo→stagflation, flipped MUST be False."""
    regime, flipped = classify_regime(
        cpi_dir=1, unrate_dir=1, gdp_dir=-1, prior_regime="stagflation",
    )
    assert regime == "stagflation"
    assert flipped is False


def test_analogue_client_requires_base_url():
    """Per project lock — env-driven, no fallback default for cross-VM URLs."""
    from agents.macro_regime_analyst.historical_analogue_client import (
        EventStudyAnalogueClient,
    )

    with pytest.raises(RuntimeError, match="VM102 base URL required"):
        EventStudyAnalogueClient(vm102_base_url="")


def test_analogue_client_degrades_on_http_failure():
    """Phase 86 outage → returns empty list (not raise)."""
    import httpx

    from agents.macro_regime_analyst.historical_analogue_client import (
        EventStudyAnalogueClient,
    )

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "phase 86 unavailable"})

    client = EventStudyAnalogueClient(vm102_base_url="http://vm102.test")
    client._client = httpx.Client(transport=httpx.MockTransport(_handler))

    analogues = client.find_analogues(
        indicator_id="CPIAUCSL", surprise=0.3,
    )
    assert analogues == [], (
        f"Expected empty list on HTTP 503, got {analogues!r}"
    )


def test_analogue_client_returns_top_3_on_success():
    """Phase 86 success → top-K HistoricalAnalogue records."""
    import httpx

    from agents.macro_regime_analyst.historical_analogue_client import (
        EventStudyAnalogueClient,
    )

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "envelope": {"sample_size": 180, "period": "2020-01-01/2025-01-01"},
                "result": {
                    "curves": [
                        {
                            "releases": [
                                {
                                    "release_id": "rel-1",
                                    "release_date": "2022-03-10",
                                    "surprise": 0.3,
                                },
                                {
                                    "release_id": "rel-2",
                                    "release_date": "2022-04-12",
                                    "surprise": 0.2,
                                },
                                {
                                    "release_id": "rel-3",
                                    "release_date": "2022-05-11",
                                    "surprise": 0.4,
                                },
                                {
                                    "release_id": "rel-4",
                                    "release_date": "2022-06-10",
                                    "surprise": 0.5,
                                },
                            ],
                        }
                    ]
                },
            },
        )

    client = EventStudyAnalogueClient(vm102_base_url="http://vm102.test")
    client._client = httpx.Client(transport=httpx.MockTransport(_handler))

    analogues = client.find_analogues(
        indicator_id="CPIAUCSL", surprise=0.3, top_k=3,
    )
    assert len(analogues) == 3, f"top_k=3 expected, got {len(analogues)}"
    assert analogues[0].release_id == "rel-1"
    assert analogues[0].sample_size == 180
    assert analogues[0].evidence_period == "2020-01-01/2025-01-01"
    assert analogues[0].indicator_id == "CPIAUCSL"
