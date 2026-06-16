"""Phase 87 Plan 10 (Wave 5b) — one-shot BeliefStore backfill from Wave 3.

RESEARCH §Wave 5 risk mitigation: when Wave 3 (Plan 87-06 macro_regime_analyst)
has been running for >1 week BEFORE Wave 5 (Plan 87-09 BeliefStore + Plan
87-10 macro_regime_monitor) ships, the BeliefStore starts cold even
though we already have several days of regime classifications. This
backfill CLI replays those ``macro_regime_classification`` rows through
``BeliefStore.propose()`` to seed the persistent state.

Idempotency: the backfill is safe to re-run. Each ``propose()`` call
carries ``evidence={"backfill_from_classification_id": <pk>}`` so the
Wave-5 BeliefStore audit trail records the provenance. Re-running the
backfill simply piles more "evidence" on the same beliefs (Beta-Bernoulli
posterior shifts further toward the observed regime) — for a true
"once-only" backfill the operator should clear the relevant beliefs
first.

Run::

    python -m scripts.backfill_belief_store_from_wave3              # live
    python -m scripts.backfill_belief_store_from_wave3 --dry-run    # count only

Env vars required (fail-fast):

    BELIEF_STORE_POSTGRES_URL  — Plan 87-09 BeliefStore
    BELIEF_STORE_MONGO_URL     — Plan 87-09 BeliefStore cache

Deviation from Plan 87-10 reference implementation (Rule 3 Blocking):
The plan specified ``VM107/management/commands/backfill_belief_store_from_wave3.py``.
VM107 has NO Django — same scripts/ adaptation as the other Plan 87-10
runners. Same env-driven fail-fast surface; same observable side effects.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys


logger = logging.getLogger(__name__)


def _env_required(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        sys.stderr.write(
            f"ERROR: env var {key} required (CLAUDE.md "
            "env-driven-no-fallbacks lock — no default)\n"
        )
        sys.exit(1)
    return value


def _build_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill BeliefStore from Wave 3 macro_regime_classification rows",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List how many rows WOULD be backfilled without writing",
    )
    return parser.parse_args(argv)


def _build_collaborators():
    """Lazy-import the BeliefStore + classification DAL.

    Heavy modules (psycopg2 connection, Mongo client) are loaded only
    when the CLI actually runs — keeps the test suite lightweight.
    """
    from core.belief.belief_store import BeliefStore  # type: ignore[import]
    from persistence.macro_regime_classification_repo import (  # type: ignore[import]
        MacroRegimeClassificationRepo,
    )
    return BeliefStore(), MacroRegimeClassificationRepo()


def backfill_belief_store(*, dry_run: bool = False) -> dict:
    """Programmatic entry point (also used by tests with stubbed DAL).

    Returns a stats dict ``{"total_rows": int, "backfilled": int,
    "skipped": int, "errors": int, "dry_run": bool}``.
    """
    bs, repo = _build_collaborators()
    rows = repo.list_since_phase87_wave3_ship_date()
    stats = {
        "total_rows": len(rows),
        "backfilled": 0,
        "skipped": 0,
        "errors": 0,
        "dry_run": bool(dry_run),
    }
    logger.info(
        {"event": "backfill_start", "total_rows": stats["total_rows"],
         "dry_run": stats["dry_run"]}
    )
    for row in rows:
        if dry_run:
            stats["backfilled"] += 1  # would-have-been
            continue
        try:
            bs.propose(
                proposer_id="macro_regime_analyst",
                subject_type="regime",
                subject_id=row["current_regime"],
                confirms_belief=True,
                evidence={
                    "backfill_from_classification_id": str(
                        row["classification_id"]
                    ),
                },
            )
            stats["backfilled"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                {"event": "backfill_row_failed",
                 "classification_id": str(row.get("classification_id")),
                 "error": str(exc)}
            )
            stats["errors"] += 1
    logger.info({"event": "backfill_complete", **stats})
    return stats


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    _env_required("BELIEF_STORE_POSTGRES_URL")
    _env_required("BELIEF_STORE_MONGO_URL")
    args = _build_args(argv)
    stats = backfill_belief_store(dry_run=args.dry_run)
    sys.stdout.write(
        f"backfill_belief_store_from_wave3: total={stats['total_rows']}, "
        f"backfilled={stats['backfilled']}, skipped={stats['skipped']}, "
        f"errors={stats['errors']}, dry_run={stats['dry_run']}\n"
    )


if __name__ == "__main__":  # pragma: no cover — exercised by the operator
    main()
