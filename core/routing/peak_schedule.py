"""
PeakSchedule — timezone-aware YAML-driven peak hour detection.

Determines whether the current time falls within any configured peak window.
Peak windows are ops-controlled configuration — NOT derived from brain.mode
(avoids feedback loops where mode influences peak which influences mode).

YAML schema (multi-window support, LOCKED per CONTEXT.md):
    routing:
      timezone: "Australia/Perth"
      peak_hours:
        - "08:00-12:00"
        - "14:00-18:00"

Peak behavior: HARD tier-shift — candidates restricted to secondary tier only.
    Even during peak, the full primary → secondary → local chain is preserved
    (peak just shifts which tier acts as "primary" for this window).

Off-peak behavior: SOFT weight boost — quality_weight *= 1.2-1.3.
    Full candidate set retained; bias toward higher-quality models.

Timezone handling: Uses stdlib zoneinfo.ZoneInfo (Python 3.12 — no pytz needed).
    DST transitions are handled correctly by ZoneInfo.

Future schema extension (schema designed for, not required in v1):
    peak_hours.weekdays: [...]
    peak_hours.weekends: [...]

Implementation plan: Plan 02 replaces stubs with real window parsing + detection.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("router.peak_schedule")


class PeakSchedule:
    """
    Timezone-aware peak hour window detector.

    Parses YAML-defined time windows and checks whether a given datetime
    (default: now in configured timezone) falls within any peak window.

    Used as Step 6 input in the routing pipeline. If is_peak() returns True,
    _apply_peak_modifier() performs a hard tier-shift to secondary tier candidates.

    Multi-window support: multiple "HH:MM-HH:MM" strings in peak_hours list.
    Windows may span midnight (e.g. "22:00-06:00") — handled correctly.

    All methods raise NotImplementedError until Plan 02 implements them.
    """

    def __init__(
        self,
        timezone: str = "Australia/Perth",
        peak_windows: list[tuple[int, int, int, int]] | None = None,
    ) -> None:
        """
        Initialize PeakSchedule.

        Args:
            timezone: IANA timezone string (e.g. "Australia/Perth")
            peak_windows: Pre-parsed windows as list of (start_hour, start_min, end_hour, end_min).
                          None means no peak hours (always off-peak).
        """
        self.timezone = timezone
        self._windows = peak_windows or []

    @classmethod
    def from_yaml(cls, routing_config: dict) -> "PeakSchedule":
        """
        Construct PeakSchedule from the 'routing' block of model_routing.yaml.

        Parses peak_hours strings ("HH:MM-HH:MM") into (start_h, start_m, end_h, end_m)
        tuples. Validates timezone via ZoneInfo before returning.

        Args:
            routing_config: Dict with keys: timezone (str), peak_hours (list[str])

        Returns:
            PeakSchedule instance with parsed windows.

        Raises:
            NotImplementedError: Until Plan 02 implements YAML parsing.
        """
        raise NotImplementedError("Phase 43 Plan 02: PeakSchedule.from_yaml() pending")

    def is_peak(self, now: Optional[datetime] = None) -> bool:
        """
        Determine if the given (or current) time falls within any peak window.

        Uses ZoneInfo to localize 'now' to the configured timezone before
        comparing against peak windows. Midnight-spanning windows handled correctly.

        Args:
            now: Datetime to check. If None, uses datetime.now(ZoneInfo(timezone)).
                 Pass timezone-aware or naive datetime (naive = assumed UTC).

        Returns:
            True if current time falls within any peak window, False otherwise.
            Returns False if no windows configured (always off-peak).

        Raises:
            NotImplementedError: Until Plan 02 implements window detection.
        """
        raise NotImplementedError("Phase 43 Plan 02: PeakSchedule.is_peak() pending")
