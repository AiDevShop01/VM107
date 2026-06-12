"""Phase 85 test fixtures — shared across Phase 85 test modules.

Provides canonical payload shapes that Wave 3 plans reuse:
- phase85_fixture_release_event_payload: Redis topic message shape for
  macro release events (Phase 83 release-event contract).
- phase85_fixture_indicator_metadata: Indicator metadata dict for CPI
  (CPIAUCSL) used by Plan 85-03 indicator-fetch and 85-08 agent prompts.
"""
import pytest

pytestmark = pytest.mark.phase_85


@pytest.fixture
def phase85_fixture_release_event_payload():
    """Canonical Phase 83 release-event Redis topic payload shape.

    Published to the `macro.release_events` channel by the Phase 83 Dagster
    OHLC post-hook when a scheduled economic release fires.  Wave 3 agents
    (Plans 85-08b / 85-09) consume this shape from Redis Pub/Sub.

    Shape mirrors Phase 83 PLAN.md § release_event_contract:
      - event_type: always "macro_release"
      - indicator_id: FRED series code (e.g. "CPIAUCSL")
      - release_timestamp: ISO-8601 UTC string
      - actual_value: float or null (null when release pending)
      - consensus_value: float or null
      - prior_value: float or null
      - revision_flag: bool — true if prior_value was revised
      - source: originating service name
    """
    return {
        "event_type": "macro_release",
        "indicator_id": "CPIAUCSL",
        "release_timestamp": "2026-06-12T12:30:00Z",
        "actual_value": 3.4,
        "consensus_value": 3.3,
        "prior_value": 3.2,
        "revision_flag": False,
        "source": "vm101.macro_calendar",
    }


@pytest.fixture
def phase85_fixture_indicator_metadata():
    """Indicator metadata dict for CPI (CPIAUCSL).

    Used by Plan 85-03 (indicator-fetch API response) and Plan 85-08b
    (agent prompt context assembly).  Shape mirrors the ref_economic_indicators
    table columns + the asset_exposure_pairs join from Phase 85 ARCHITECTURE.md.
    """
    return {
        "indicator_id": "CPIAUCSL",
        "formula": "CPI-U: All Urban Consumers, All Items, Seasonally Adjusted",
        "components": [
            "Housing",
            "Transportation",
            "Food and Beverages",
            "Medical Care",
            "Education and Communication",
        ],
        "importance": "HIGH",
        "regime_thresholds": [
            {"label": "deflationary", "upper_bound": 1.0},
            {"label": "low_inflation", "lower_bound": 1.0, "upper_bound": 2.5},
            {"label": "target_inflation", "lower_bound": 2.5, "upper_bound": 3.5},
            {"label": "elevated_inflation", "lower_bound": 3.5, "upper_bound": 5.0},
            {"label": "high_inflation", "lower_bound": 5.0},
        ],
        "asset_exposure_pairs": [
            {
                "asset": "DXY",
                "default_direction": "POS",
                "ohlc_symbol": "DXY",
            },
            {
                "asset": "GOLD",
                "default_direction": "NEG",
                "ohlc_symbol": "XAUUSD",
            },
            {
                "asset": "SPX",
                "default_direction": "NEG",
                "ohlc_symbol": "US500",
            },
        ],
    }
