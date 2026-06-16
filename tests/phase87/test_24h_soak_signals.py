"""Phase 87 Wave 8 — 24h soak signal harness (REQ-87-4 + AC-87-4 + LOCK-3).

This file is the soak-harness wiring, NOT a 24h pytest run. The actual 24h
soak executes externally on dev VM107 (the macro_story_tracker hourly +
macro_regime_monitor 6h cadences run for 24 wall-clock hours). What this
harness ships:

  1. assert_soak_results(report_path) — validates a soak-report JSON
     produced by the external runner.
  2. test_soak_harness_runnable — sanity test that imports + dataclass
     contracts parse, no actual soak required.
  3. test_soak_with_synthetic_report — if a soak-report fixture is present
     at tests/phase87/fixtures/soak_24h_report.json (produced by Plan 87-14
     Task 2 manual UAT), runs the assertions against it. Otherwise xfail
     (so the harness is provably wired without forcing a 24h delay on
     every pytest run).

Soak success criteria (per plan must_haves):
  - >=3 active stories in macro_story table at the end (REQ-87-4 + AC-87-4)
  - zero ERROR / CRITICAL telemetry events
  - zero pathological transitions (LOCK-3 0.65 threshold calibration: false-
    positive transitions should be <=1 over 24h)
  - macro_story_tracker hourly cycles: 24 (one per hour, +/- 1 for boundaries)
  - macro_regime_monitor 6h cycles: 4 (+/- 1 for boundary)
  - P95 monitor tick latency < 90s

External runner spec (referenced from Plan 87-14 Task 3 deploy step):
  - inject synthetic econ_release for each of LOCK-1's 12 seed indicators
    on a randomised hourly schedule
  - capture story_tracker outputs at each hourly tick
  - capture regime_monitor outputs at each 6h tick
  - capture all ERROR/CRITICAL telemetry to telemetry.log
  - persist final macro_story snapshot + regime_transition_events list
  - emit a JSON report at tests/phase87/fixtures/soak_24h_report.json with
    the schema below.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.phase_87

# Soak success thresholds — locked here so the harness is the single source of
# truth for what counts as a green 24h soak.
REQ_87_4_MIN_ACTIVE_STORIES: int = 3              # REQ-87-4 / AC-87-4
LOCK_3_MAX_FALSE_POSITIVE_TRANSITIONS: int = 1    # LOCK-3 0.65 calibration
EXPECTED_HOURLY_TICKS: int = 24                   # 24h × 1/h
EXPECTED_HOURLY_TICKS_TOLERANCE: int = 1          # boundary slack
EXPECTED_6H_TICKS: int = 4                        # 24h ÷ 6h
EXPECTED_6H_TICKS_TOLERANCE: int = 1              # boundary slack
P95_MONITOR_TICK_LATENCY_MAX_S: float = 90.0      # SLO for the 6h tick


@dataclass(frozen=True)
class SoakReport:
    """Parsed soak-report JSON.

    Mirrored on-disk schema (tests/phase87/fixtures/soak_24h_report.json):
      {
        "soak_started_at": ISO-8601,
        "soak_ended_at": ISO-8601,
        "active_story_count": int,
        "retired_story_count": int,
        "false_positive_transitions": int,
        "regime_transitions_emitted": int,
        "story_tracker_tick_count": int,
        "regime_monitor_tick_count": int,
        "telemetry_error_count": int,
        "telemetry_critical_count": int,
        "regime_monitor_p95_latency_s": float,
        "synthetic_release_indicators": [str, ...]   # the 12 seed indicators
      }
    """

    soak_started_at: str
    soak_ended_at: str
    active_story_count: int
    retired_story_count: int
    false_positive_transitions: int
    regime_transitions_emitted: int
    story_tracker_tick_count: int
    regime_monitor_tick_count: int
    telemetry_error_count: int
    telemetry_critical_count: int
    regime_monitor_p95_latency_s: float
    synthetic_release_indicators: list[str] = field(default_factory=list)

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "SoakReport":
        return cls(
            soak_started_at=str(payload["soak_started_at"]),
            soak_ended_at=str(payload["soak_ended_at"]),
            active_story_count=int(payload["active_story_count"]),
            retired_story_count=int(payload.get("retired_story_count", 0)),
            false_positive_transitions=int(payload.get("false_positive_transitions", 0)),
            regime_transitions_emitted=int(payload.get("regime_transitions_emitted", 0)),
            story_tracker_tick_count=int(payload["story_tracker_tick_count"]),
            regime_monitor_tick_count=int(payload["regime_monitor_tick_count"]),
            telemetry_error_count=int(payload.get("telemetry_error_count", 0)),
            telemetry_critical_count=int(payload.get("telemetry_critical_count", 0)),
            regime_monitor_p95_latency_s=float(
                payload.get("regime_monitor_p95_latency_s", 0.0)
            ),
            synthetic_release_indicators=list(
                payload.get("synthetic_release_indicators", [])
            ),
        )


def assert_soak_results(report: SoakReport) -> None:
    """Apply all Wave 8 soak success criteria to a SoakReport.

    Raises AssertionError with a per-criterion message on first failure;
    re-runnable so any operator can confirm a soak-report passes by calling
    this directly on the JSON.
    """
    # REQ-87-4 / AC-87-4 — >=3 active stories
    assert report.active_story_count >= REQ_87_4_MIN_ACTIVE_STORIES, (
        f"REQ-87-4 / AC-87-4 — expected >={REQ_87_4_MIN_ACTIVE_STORIES} "
        f"active stories at soak end, got {report.active_story_count}"
    )

    # LOCK-3 0.65 threshold calibration
    assert (
        report.false_positive_transitions <= LOCK_3_MAX_FALSE_POSITIVE_TRANSITIONS
    ), (
        f"LOCK-3 0.65 threshold calibration — "
        f"expected <={LOCK_3_MAX_FALSE_POSITIVE_TRANSITIONS} false-positive "
        f"transitions over 24h, got {report.false_positive_transitions}. "
        "If consistently exceeded, update LOCK-3 in 87-CONTEXT.md per RESEARCH "
        "§Wave 5 risk register."
    )

    # Zero ERROR / CRITICAL telemetry
    assert report.telemetry_error_count == 0, (
        f"Soak telemetry had {report.telemetry_error_count} ERROR events — "
        "must be zero before prod deploy"
    )
    assert report.telemetry_critical_count == 0, (
        f"Soak telemetry had {report.telemetry_critical_count} CRITICAL events — "
        "must be zero before prod deploy"
    )

    # Tick count plausibility
    hourly_low = EXPECTED_HOURLY_TICKS - EXPECTED_HOURLY_TICKS_TOLERANCE
    hourly_high = EXPECTED_HOURLY_TICKS + EXPECTED_HOURLY_TICKS_TOLERANCE
    assert hourly_low <= report.story_tracker_tick_count <= hourly_high, (
        f"story_tracker hourly tick count out of band: expected "
        f"[{hourly_low}, {hourly_high}], got {report.story_tracker_tick_count}"
    )

    six_h_low = EXPECTED_6H_TICKS - EXPECTED_6H_TICKS_TOLERANCE
    six_h_high = EXPECTED_6H_TICKS + EXPECTED_6H_TICKS_TOLERANCE
    assert six_h_low <= report.regime_monitor_tick_count <= six_h_high, (
        f"regime_monitor 6h tick count out of band: expected "
        f"[{six_h_low}, {six_h_high}], got {report.regime_monitor_tick_count}"
    )

    # Monitor latency SLO
    assert (
        report.regime_monitor_p95_latency_s < P95_MONITOR_TICK_LATENCY_MAX_S
    ), (
        f"regime_monitor P95 tick latency {report.regime_monitor_p95_latency_s:.2f}s "
        f"exceeds {P95_MONITOR_TICK_LATENCY_MAX_S}s SLO"
    )


# ─── Unit-level harness sanity ────────────────────────────────────────────────
def test_soak_harness_dataclass_round_trip() -> None:
    """SoakReport round-trips from a plausible JSON payload."""
    sample = {
        "soak_started_at": "2026-06-16T00:00:00Z",
        "soak_ended_at": "2026-06-17T00:00:00Z",
        "active_story_count": 4,
        "retired_story_count": 1,
        "false_positive_transitions": 0,
        "regime_transitions_emitted": 1,
        "story_tracker_tick_count": 24,
        "regime_monitor_tick_count": 4,
        "telemetry_error_count": 0,
        "telemetry_critical_count": 0,
        "regime_monitor_p95_latency_s": 12.4,
        "synthetic_release_indicators": [
            "CPIAUCSL", "PPI", "NFP", "UNRATE", "FEDFUNDS",
            "GDP", "RetailSales", "ECB_RATE", "BOJDFR", "PMI",
            "ISM", "DGS10",
        ],
    }
    report = SoakReport.from_json(sample)
    assert report.active_story_count == 4
    assert len(report.synthetic_release_indicators) == 12
    # Should pass all assertions
    assert_soak_results(report)


def test_assert_soak_results_catches_insufficient_stories() -> None:
    """Calibration: <3 active stories fails REQ-87-4."""
    report = SoakReport(
        soak_started_at="2026-06-16T00:00:00Z",
        soak_ended_at="2026-06-17T00:00:00Z",
        active_story_count=2,  # <-- the failure
        retired_story_count=0,
        false_positive_transitions=0,
        regime_transitions_emitted=0,
        story_tracker_tick_count=24,
        regime_monitor_tick_count=4,
        telemetry_error_count=0,
        telemetry_critical_count=0,
        regime_monitor_p95_latency_s=10.0,
    )
    with pytest.raises(AssertionError, match="REQ-87-4 / AC-87-4"):
        assert_soak_results(report)


def test_assert_soak_results_catches_pathological_transitions() -> None:
    """Calibration: too-many false-positive transitions fails LOCK-3."""
    report = SoakReport(
        soak_started_at="2026-06-16T00:00:00Z",
        soak_ended_at="2026-06-17T00:00:00Z",
        active_story_count=3,
        retired_story_count=0,
        false_positive_transitions=5,  # <-- the failure
        regime_transitions_emitted=5,
        story_tracker_tick_count=24,
        regime_monitor_tick_count=4,
        telemetry_error_count=0,
        telemetry_critical_count=0,
        regime_monitor_p95_latency_s=10.0,
    )
    with pytest.raises(AssertionError, match="LOCK-3"):
        assert_soak_results(report)


def test_assert_soak_results_catches_error_telemetry() -> None:
    """Calibration: any ERROR telemetry fails the soak."""
    report = SoakReport(
        soak_started_at="2026-06-16T00:00:00Z",
        soak_ended_at="2026-06-17T00:00:00Z",
        active_story_count=3,
        retired_story_count=0,
        false_positive_transitions=0,
        regime_transitions_emitted=1,
        story_tracker_tick_count=24,
        regime_monitor_tick_count=4,
        telemetry_error_count=1,  # <-- the failure
        telemetry_critical_count=0,
        regime_monitor_p95_latency_s=10.0,
    )
    with pytest.raises(AssertionError, match="ERROR events"):
        assert_soak_results(report)


# ─── External soak-report consumer ────────────────────────────────────────────
_SOAK_REPORT_PATH = Path(__file__).parent / "fixtures" / "soak_24h_report.json"


def test_24h_soak_report_passes_if_present() -> None:
    """If a 24h soak report has been written, validate it.

    The external soak runner (Plan 87-14 Task 2 manual UAT) writes the report
    to tests/phase87/fixtures/soak_24h_report.json. When the report is absent
    (e.g., during plan execution before the soak has been run), this test
    xfails — the harness is provably wired without forcing a 24h delay.
    """
    if not _SOAK_REPORT_PATH.exists():
        pytest.xfail(
            f"No 24h soak report at {_SOAK_REPORT_PATH} — the external soak "
            "harness has not been run yet (run during Plan 87-14 Task 2 UAT)."
        )
    payload = json.loads(_SOAK_REPORT_PATH.read_text())
    report = SoakReport.from_json(payload)
    assert_soak_results(report)
