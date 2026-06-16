"""Phase 87 Wave 4b — docker healthcheck for the macro_story_tracker.

Returns exit 0 when the last successful tick was within 90 minutes
(hourly cron at minute 5 + 30-minute buffer for tick duration / clock
drift). Returns exit 1 otherwise (the sibling service's restart policy
then handles container recovery).

Used by the ``healthcheck.test`` in ``docker-compose.yml``::

    healthcheck:
      test: ["CMD", "python", "-m", "scripts.macro_story_tracker_health"]
      interval: 5m
      timeout: 30s
      retries: 3

Deviation from Plan 87-08 reference implementation (Rule 3 Blocking):
The plan specified ``VM107/management/commands/macro_story_tracker_health.py``
(Django management command). VM107 has NO Django — adapted to the in-repo
``python -m scripts.*`` CLI pattern matching ``run_macro_story_tracker.py``.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timedelta, timezone

# Must match LAST_RUN_FILE in scripts/run_macro_story_tracker.py.
LAST_RUN_FILE = pathlib.Path("/app/logs/macro_story_tracker_last_run.iso")

# Hourly cadence (60min) + 30min buffer for tick duration / clock drift.
MAX_STALENESS = timedelta(minutes=90)


def _main() -> int:
    if not LAST_RUN_FILE.exists():
        sys.stderr.write(
            f"unhealthy: heartbeat file {LAST_RUN_FILE} does not exist "
            "(tracker has not completed a tick yet)\n"
        )
        return 1
    raw = LAST_RUN_FILE.read_text().strip()
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError as exc:
        sys.stderr.write(
            f"unhealthy: heartbeat file {LAST_RUN_FILE} contained "
            f"non-ISO-8601 content {raw!r}: {exc}\n"
        )
        return 1
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    age = datetime.now(tz=timezone.utc) - ts
    if age > MAX_STALENESS:
        sys.stderr.write(
            f"unhealthy: last tick {ts.isoformat()} is "
            f"{int(age.total_seconds()/60)} min ago (>90 min threshold)\n"
        )
        return 1

    sys.stdout.write(
        f"healthy: last tick {ts.isoformat()} "
        f"({int(age.total_seconds()/60)} min ago)\n"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — exercised by docker healthcheck
    sys.exit(_main())
