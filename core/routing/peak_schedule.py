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

Off-peak behavior: SOFT weight boost — quality_weight *= 1.25 (midpoint of 1.2-1.3 range).
    Full candidate set retained; bias toward higher-quality models.

Timezone handling: Uses stdlib zoneinfo.ZoneInfo (Python 3.9+ — no pytz needed).
    DST transitions are handled correctly by ZoneInfo.

Future schema extension (schema designed for, not required in v1):
    peak_hours.weekdays: [...]
    peak_hours.weekends: [...]
"""
from __future__ import annotations

import logging
from datetime import datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("router.peak_schedule")


class PeakSchedule:
    """
    Timezone-aware peak hour window detector.

    Parses YAML-defined time windows and checks whether a given datetime
    (default: now in configured timezone) falls within any peak window.

    Used as Step 6 input in the routing pipeline. If is_peak() returns True,
    _apply_peak_modifier() performs a hard tier-shift to secondary tier candidates.

    Multi-window support: multiple "HH:MM-HH:MM" strings in peak_hours list.
    Window matching uses start <= t < end semantics (exclusive end boundary).
    """

    def __init__(
        self,
        timezone: str = "Australia/Perth",
        windows: list[str] | None = None,
    ) -> None:
        """
        Initialize PeakSchedule.

        Args:
            timezone: IANA timezone string (e.g. "Australia/Perth").
            windows: List of window strings in "HH:MM-HH:MM" format.
                     Empty list means no peak hours (always off-peak).

        Raises:
            ZoneInfoNotFoundError: If timezone string is not a valid IANA timezone.
        """
        self.tz = ZoneInfo(timezone)
        self.windows: list[tuple[time, time]] = []
        for w in (windows or []):
            start_str, end_str = w.split("-")
            self.windows.append((self._parse_time(start_str), self._parse_time(end_str)))

    @classmethod
    def from_yaml(cls, routing_config: dict) -> "PeakSchedule":
        """
        Construct PeakSchedule from the 'routing' block of model_routing.yaml.

        Parses peak_hours strings ("HH:MM-HH:MM") into (start_time, end_time)
        pairs using stdlib time objects. Validates timezone via ZoneInfo before returning.

        Args:
            routing_config: Dict with keys: timezone (str), peak_hours (list[str]).
                           This is the value of `config["routing"]` from model_routing.yaml.

        Returns:
            PeakSchedule instance with parsed windows.

        Raises:
            ZoneInfoNotFoundError: If timezone is not a valid IANA timezone.
        """
        return cls(
            timezone=routing_config["timezone"],
            windows=routing_config.get("peak_hours", []),
        )

    @staticmethod
    def _parse_time(s: str) -> time:
        """Parse "HH:MM" string into a time object."""
        h, m = s.strip().split(":")
        return time(int(h), int(m))

    def is_peak(self, now: Optional[datetime] = None) -> bool:
        """
        Determine if the given (or current) time falls within any peak window.

        Uses ZoneInfo to localize 'now' to the configured timezone before
        comparing against peak windows. Uses start <= t < end semantics.

        Args:
            now: Datetime to check. If None, uses datetime.now(self.tz).
                 Timezone-aware datetimes are converted to the configured timezone.
                 Naive datetimes are treated as if in the configured timezone.

        Returns:
            True if current time falls within any peak window, False otherwise.
            Returns False if no windows configured (always off-peak).
        """
        if not self.windows:
            return False

        if now is None:
            now = datetime.now(self.tz)
        elif now.tzinfo is None:
            # Naive datetime: assume it's in the configured timezone
            now = now.replace(tzinfo=self.tz)
        else:
            # Timezone-aware: convert to configured timezone
            now = now.astimezone(self.tz)

        t = now.time()
        for start, end in self.windows:
            if start <= t < end:
                logger.debug(
                    "is_peak=True: %s falls in window %s-%s (%s)",
                    t, start, end, self.tz,
                )
                return True

        return False
