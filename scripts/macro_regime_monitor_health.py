"""Phase 87 Plan 10 (Wave 5b) — docker healthcheck for macro_regime_monitor.

Returns exit 0 when the last successful tick was within 7 hours (6h cron
+ 1h buffer for tick duration / clock drift). Returns exit 1 otherwise
(the sibling service's restart policy then handles container recovery).

Used by the ``healthcheck.test`` in ``docker-compose.yml``::

    healthcheck:
      test: ["CMD", "python", "-m", "scripts.macro_regime_monitor_health"]
      interval: 10m
      timeout: 30s
      retries: 3

Deviation from Plan 87-10 reference implementation (Rule 3 Blocking):
The plan specified ``VM107/management/commands/macro_regime_monitor_health.py``
(Django management command). VM107 has NO Django — adapted to the in-repo
``python -m scripts.*`` CLI pattern matching Plan 87-08's
``scripts/macro_story_tracker_health.py`` precedent.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timedelta, timezone

# Must match LAST_RUN_FILE in scripts/run_macro_regime_monitor.py.
LAST_RUN_FILE = pathlib.Path("/app/logs/macro_regime_monitor_last_run.iso")

# 6-hourly cadence + 1h buffer for tick duration / clock drift.
MAX_STALENESS = timedelta(hours=7)


def _main() -> int:
    if not LAST_RUN_FILE.exists():
        sys.stderr.write(
            f"unhealthy: heartbeat file {LAST_RUN_FILE} does not exist "
            "(monitor has not completed a tick yet)\n"
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
            f"{int(age.total_seconds() / 60)} min ago (>7h threshold)\n"
        )
        return 1

    sys.stdout.write(
        f"healthy: last tick {ts.isoformat()} "
        f"({int(age.total_seconds() / 60)} min ago)\n"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — exercised by docker healthcheck
    sys.exit(_main())
