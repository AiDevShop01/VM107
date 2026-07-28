"""Docker healthcheck for the vm107-cost-monitor sibling service.

Returns exit 0 when the last successful tick was within the staleness window
(the tick interval plus a generous buffer for tick duration / clock drift).
Returns exit 1 otherwise (the sibling service's restart policy then handles
container recovery).

Used by the ``healthcheck.test`` in ``docker-compose.yml``::

    healthcheck:
      test: ["CMD", "/opt/venv-a0/bin/python", "-m", "scripts.cost_monitor_health"]

Mirrors ``scripts/macro_regime_monitor_health.py`` (Phase 87 Plan 10).
"""
from __future__ import annotations

import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone

# Must match LAST_RUN_FILE in scripts/run_cost_monitor.py.
LAST_RUN_FILE = pathlib.Path("/app/logs/cost_monitor_last_run.iso")

# Tick cadence (default 300s) plus a buffer for tick duration / clock drift.
# Buffer = max(tick interval, 300s) so a slow tick never trips a false unhealthy.
_INTERVAL_SEC = int(os.environ.get("COST_MONITOR_INTERVAL_SEC", "300"))
MAX_STALENESS = timedelta(seconds=_INTERVAL_SEC) + timedelta(seconds=max(_INTERVAL_SEC, 300))


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
            f"{int(age.total_seconds() / 60)} min ago "
            f"(> {int(MAX_STALENESS.total_seconds() / 60)}min threshold)\n"
        )
        return 1

    sys.stdout.write(
        f"healthy: last tick {ts.isoformat()} "
        f"({int(age.total_seconds() / 60)} min ago)\n"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — exercised by docker healthcheck
    sys.exit(_main())
