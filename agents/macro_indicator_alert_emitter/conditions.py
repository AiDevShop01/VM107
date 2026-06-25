"""Phase 91 Plan 2 Task 2 — Per-indicator default condition catalog.

For each Tier-1 FRED indicator, a tier list of default thresholds the emitter
fires on. Each entry:
  - id        : stable string used as the per-condition idempotency seed
                (event_id = sha256(indicator_id|release_date|condition_id)[:16]).
                MUST be unique across all conditions of a single indicator —
                duplicate ids collide event_ids on the VM100 intake side.
  - expr      : DSL expression evaluated locally by the emitter to decide
                whether the condition matches. References the same namespace
                keys that mission_control.services.macro_release_intake
                produces — short name (CPI / NFP / UNRATE / FEDFUNDS / PPI)
                plus prev_ / surprise_ / pct_ prefixes.
  - severity  : B13 internal severity (info / warning / blocking) — translated
                to Phase 91 Title-Case (Info / Important / Critical) inside
                emit_alert_candidate.
  - template  : Human-readable explanation. format() applied with the same
                namespace; reference values via short name (e.g. {CPI:.2f}).

Adding an indicator requires:
  1. Adding the FRED id to INDICATOR_DEFAULT_CONDITIONS below
  2. Adding the short-name mapping in
     VM100/backend/mission_control/services/macro_release_intake.INDICATOR_SHORT_NAMES
     (so the VM100 evaluator namespace uses the same short alias)

Tier rationale (default thresholds — user subscriptions override per their
own DSL via the AlertDefinition.condition_yaml field):

  CPI    > 4% / > 5%        → above-target / critical inflation
  CPI    surprise >= 0.3    → consensus miss that moves markets
  NFP    > 250k / < 100k    → strong / weak labour print
  NFP    surprise >= 0.5    → consensus miss
  UNRATE > 5%               → softening labour market
  UNRATE crosses_above 4%   → trend inflection
  FEDFUNDS surprise >= 0.5  → unexpected Fed action
  PPI    > 4%               → producer-side inflation
"""
from __future__ import annotations

from typing import Any


# Per-indicator default condition tiers. Plan 2 ships the 5 Tier-1 indicators;
# Plan 3 / Plan 6 may add Tier-2 / Tier-3 indicators here.
INDICATOR_DEFAULT_CONDITIONS: dict[str, list[dict[str, Any]]] = {
    "CPIAUCSL": [
        {
            "id": "cpi_gt_4",
            "expr": "CPI is not None and CPI > 4",
            "severity": "warning",  # → Important
            "template": "CPI {CPI:.2f}% — above 4% threshold",
        },
        {
            "id": "cpi_gt_5",
            "expr": "CPI is not None and CPI > 5",
            "severity": "blocking",  # → Critical
            "template": "CPI {CPI:.2f}% — CRITICAL above 5%",
        },
        {
            "id": "cpi_surprise_0_3",
            "expr": "surprise_CPI is not None and abs(surprise_CPI) >= 0.3",
            "severity": "warning",
            "template": "CPI surprise {surprise_CPI:.3f} above consensus magnitude",
        },
    ],
    "PAYEMS": [
        {
            "id": "nfp_gt_250k",
            "expr": "NFP is not None and NFP > 250000",
            "severity": "warning",
            "template": "NFP {NFP:.0f} — strong print above 250k",
        },
        {
            "id": "nfp_lt_100k",
            "expr": "NFP is not None and NFP < 100000",
            "severity": "warning",
            "template": "NFP {NFP:.0f} — weak print below 100k",
        },
        {
            "id": "nfp_surprise_0_5",
            "expr": "surprise_NFP is not None and abs(surprise_NFP) >= 0.5",
            "severity": "warning",
            "template": "NFP surprise {surprise_NFP:.3f} above consensus magnitude",
        },
    ],
    "UNRATE": [
        {
            "id": "unrate_gt_5",
            "expr": "UNRATE is not None and UNRATE > 5",
            "severity": "warning",
            "template": "UNRATE {UNRATE:.2f}% — labour market softening above 5%",
        },
        {
            "id": "unrate_crosses_above_4",
            "expr": "prev_UNRATE is not None and prev_UNRATE < 4 and UNRATE >= 4",
            "severity": "warning",
            "template": "UNRATE crossed above 4% ({prev_UNRATE:.2f} → {UNRATE:.2f})",
        },
    ],
    "FEDFUNDS": [
        {
            "id": "fedfunds_surprise_0_5",
            "expr": "surprise_FEDFUNDS is not None and abs(surprise_FEDFUNDS) >= 0.5",
            "severity": "blocking",  # Fed surprises are P1
            "template": "FEDFUNDS surprise {surprise_FEDFUNDS:.3f} — unexpected Fed action",
        },
    ],
    "PPIACO": [
        {
            "id": "ppi_gt_4",
            "expr": "PPI is not None and PPI > 4",
            "severity": "warning",
            "template": "PPI {PPI:.2f}% — producer inflation above 4%",
        },
    ],
}


# Always-fire info-severity condition per indicator — guarantees subscriptions
# with custom DSL get a chance to match even when no default tier triggers.
# event_id is keyed on this id so we still get one envelope per (release, user)
# instead of dropping releases entirely when no default tier fires.
RELEASE_LANDED_INFO_CONDITION: dict[str, Any] = {
    "id": "release_landed",
    "expr": "True",
    "severity": "info",
    "template": "{short_name} release {value} (prev {prev_value})",
}


__all__ = ["INDICATOR_DEFAULT_CONDITIONS", "RELEASE_LANDED_INFO_CONDITION"]
