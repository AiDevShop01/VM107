"""Phase 85.1 — Persistence alias for economic_event executive summary.

Provides ``update_summary(event_id, ai_executive_summary_text)`` — the
canonical function name used by the Phase 85.1 dispatcher routing layer
(VM107/workers/output_routing.py) and its tests.

Delegates to ``economic_event_summary.write_summary`` (Plan 85-09) which
performs the actual psycopg2 UPDATE against the tradetracker DB.

Why this file exists:
    Plan 85-09 shipped ``economic_event_summary.write_summary`` with the
    signature ``write_summary(event_id, summary_text)``.  Phase 85.1 Plan 02
    introduced a cleaner API surface: ``update_summary(event_id,
    ai_executive_summary_text)`` to make the purpose of each kwarg explicit
    in dispatcher call sites.  This thin shim keeps the Plan-09 module
    unchanged while giving Plan-02/05 tests a stable patch target.
"""
from __future__ import annotations

from persistence.economic_event_summary import write_summary


def update_summary(event_id: str, ai_executive_summary_text: str) -> None:
    """UPDATE economic_event.ai_executive_summary for the given event_id.

    Thin wrapper over ``economic_event_summary.write_summary``.  See that
    module for full contract, error handling, and DB-connection notes.

    Args:
        event_id: Unique event identifier (e.g. "CPIAUCSL:2026-06-12T12:30:00Z").
        ai_executive_summary_text: The ~50-word executive summary produced by
            the macro_executive_summary_writer agent.

    Raises:
        RuntimeError: if 0 rows affected (event not found or wrong DB).
        RuntimeError: if any required POSTGRES_* env var is missing.
        psycopg2.Error: on any DB error.
    """
    write_summary(event_id=event_id, summary_text=ai_executive_summary_text)
