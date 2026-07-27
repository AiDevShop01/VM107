"""Plan 87-14 deploy-gate DAL — macro_regime_classification read model.

Completes the Plan 87-14 wiring for ``vm107-macro-regime-monitor``. The runner
(``scripts/run_macro_regime_monitor.py``) imports
``persistence.macro_regime_classification_repo.MacroRegimeClassificationRepo``
and the agent calls ``most_recent_regime()`` (see
``agents/macro_regime_monitor/agent.py`` — ``_current_regime``) to seed the
cold-start regime.

DAL pattern mirrors ``persistence/economic_event_summary.py`` (psycopg2 direct,
no ORM) with ONE critical difference:

  ⚠ macro_regime_classification lives in **tradetracker_analytics**, NOT
    tradetracker. Verified by live introspection 2026-07-27 — the table is
    absent from tradetracker. Therefore this DAL uses ``get_analytics_conn()``
    (NOT ``get_default_conn()``). Using get_default_conn() would connect to
    tradetracker and raise "relation does not exist" / silently match nothing
    (the exact config-drift trap economic_event_summary.py warns about).

Live schema (tradetracker_analytics.macro_regime_classification):
    classification_id uuid, event_id uuid, indicator_id varchar,
    current_regime varchar, prior_regime varchar, transition_probability float8,
    confidence float8, supporting_evidence jsonb, envelope_id uuid,
    b1_artifact_id uuid, degraded boolean, generated_at timestamptz

Import safety: the psycopg2 / services import is deferred to call time so that
merely importing this module (deploy-gate guard, pytest collection) never
requires psycopg2 to be installed. The agent already wraps most_recent_regime()
in try/except and falls back to its cold-start regime on any error.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)

# Ordering column for "most recent" — the row write timestamp.
_MOST_RECENT_SQL = (
    "SELECT current_regime "
    "FROM macro_regime_classification "
    "WHERE current_regime IS NOT NULL "
    "ORDER BY generated_at DESC "
    "LIMIT 1"
)


class MacroRegimeClassificationRepo:
    """Read-only DAL over tradetracker_analytics.macro_regime_classification."""

    def most_recent_regime(self) -> Optional[str]:
        """Return the most recently classified ``current_regime``, or None.

        None means the table is empty (no classification has been persisted
        yet) or unreadable — the caller cold-starts in that case. Never raises
        for the empty-table case; connection/query errors propagate to the
        agent's own try/except guard.
        """
        # Deferred import — keeps module import free of psycopg2 (see docstring).
        from services.postgres_analytics_client import get_analytics_conn

        conn = get_analytics_conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(_MOST_RECENT_SQL)
                row = cur.fetchone()
            finally:
                cur.close()
        finally:
            conn.close()

        if not row or row[0] is None:
            return None
        return str(row[0])
