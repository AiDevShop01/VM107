"""Plan 87-14 deploy-gate DAL — tradetracker.macro_story write model.

Completes the Plan 87-14 wiring for ``vm107-macro-story-tracker``. The runner
(``scripts/run_macro_story_tracker.py``) imports
``persist.macro_story_repo.MacroStoryRepo`` and the agent
(``agents/macro_story_tracker/agent.py``) calls the four methods below across
its CREATE / REINFORCE / RETIRE decision paths and the active-story scan.

DAL pattern mirrors ``persistence/economic_event_summary.py`` (psycopg2 direct,
no ORM). macro_story lives in **tradetracker** (verified by live introspection
2026-07-27 — table present, 0 rows), so this DAL uses ``get_default_conn()``
(NOT get_analytics_conn()).

Live schema (tradetracker.macro_story):
    story_id uuid PK, headline text, headline_embedding jsonb,
    created_at timestamptz, last_reinforced_at timestamptz,
    supporting_releases jsonb, supporting_indicators jsonb,
    confidence float8, is_active boolean, retired_at timestamptz,
    retirement_reason text, generated_by_envelope_id uuid,
    supersedes_story_id uuid

Import safety: psycopg2 / services imports are deferred to call time so the
deploy-gate guard (and pytest collection) can import this module without
psycopg2 installed. ``__init__`` opens NO connection.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger(__name__)


class MacroStoryRepo:
    """Read/write DAL over tradetracker.macro_story."""

    def _conn(self):
        # Deferred import — keeps module import free of psycopg2 (see docstring).
        from services.postgres_analytics_client import get_default_conn

        return get_default_conn()

    def list_active(self) -> list[dict[str, Any]]:
        """Return all active stories (is_active = true), newest first.

        Each row is a dict keyed by column name. The tracker reads
        ``story_id`` (to retire/reinforce) plus the supporting sets and
        confidence; return the full working set so callers never re-query.
        """
        sql = (
            "SELECT story_id, headline, supporting_releases, "
            "supporting_indicators, confidence, created_at, last_reinforced_at "
            "FROM macro_story WHERE is_active = TRUE "
            "ORDER BY last_reinforced_at DESC NULLS LAST, created_at DESC"
        )
        conn = self._conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(sql)
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
            finally:
                cur.close()
        finally:
            conn.close()
        return [
            {c: (str(v) if c == "story_id" else v) for c, v in zip(cols, row)}
            for row in rows
        ]

    def create(
        self,
        *,
        story_id: str,
        headline: str,
        headline_embedding: list[float],
        supporting_releases: list,
        supporting_indicators: list,
        confidence: float,
        generated_by_envelope_id: str,
    ) -> None:
        """Insert a new active story. created_at / last_reinforced_at = now().

        macro_story.generated_by_envelope_id is NOT NULL — the agent's CREATE
        path always persists the envelope first (envelope_repo.persist) and
        passes its id here, so a null would be a genuine upstream bug and the
        DB constraint should reject it loudly rather than write an orphan row.
        """
        from psycopg2.extras import Json

        sql = (
            "INSERT INTO macro_story "
            "(story_id, headline, headline_embedding, supporting_releases, "
            " supporting_indicators, confidence, is_active, created_at, "
            " last_reinforced_at, generated_by_envelope_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, TRUE, now(), now(), %s)"
        )
        conn = self._conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    sql,
                    (
                        story_id,
                        headline,
                        Json(headline_embedding or []),
                        Json(list(supporting_releases or [])),
                        Json(list(supporting_indicators or [])),
                        confidence,
                        generated_by_envelope_id,
                    ),
                )
                conn.commit()
            finally:
                cur.close()
        finally:
            conn.close()

    def reinforce(
        self,
        *,
        story_id: str,
        add_release_id: Optional[str],
        add_indicators: list,
    ) -> None:
        """Append a release + indicators to an existing story; bump the
        last_reinforced_at timestamp. jsonb-array concat; no-op-safe on empty
        additions."""
        from psycopg2.extras import Json

        sql = (
            "UPDATE macro_story SET "
            "supporting_releases = COALESCE(supporting_releases, '[]'::jsonb) || %s::jsonb, "
            "supporting_indicators = COALESCE(supporting_indicators, '[]'::jsonb) || %s::jsonb, "
            "last_reinforced_at = now() "
            "WHERE story_id = %s AND is_active = TRUE"
        )
        add_releases = [add_release_id] if add_release_id is not None else []
        conn = self._conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    sql,
                    (Json(add_releases), Json(list(add_indicators or [])), story_id),
                )
                conn.commit()
            finally:
                cur.close()
        finally:
            conn.close()

    def retire(self, *, story_id: str, reason: str) -> None:
        """Mark a story inactive with a retirement reason + timestamp."""
        sql = (
            "UPDATE macro_story SET is_active = FALSE, retired_at = now(), "
            "retirement_reason = %s WHERE story_id = %s AND is_active = TRUE"
        )
        conn = self._conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(sql, (reason, story_id))
                conn.commit()
            finally:
                cur.close()
        finally:
            conn.close()
