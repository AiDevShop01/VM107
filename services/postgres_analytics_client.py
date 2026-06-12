"""psycopg2 connection factories for Phase 85 DB writes.

Two factories are provided:
- get_analytics_conn() → tradetracker_analytics (B1 row writes — Plan 85-02)
- get_default_conn()   → tradetracker (economic_event UPDATE — Plan 85-09)

Both use the same fail-fast _required() pattern (env-driven-no-fallbacks lock,
CLAUDE.md). No fallback defaults — misconfiguration surfaces immediately at
call time rather than silently writing to the wrong DB.

Callers manage commit/close — no connection pooling in this plan.
psycopg2-binary added to requirements.txt at Phase 85 Plan 01.
"""
from __future__ import annotations

import os

import psycopg2


# ─────────────────────────────────────────────────────────────────────────────
# Fail-fast env var resolution
# ─────────────────────────────────────────────────────────────────────────────

def _required(key: str) -> str:
    """Return env var value or raise RuntimeError. No fallback defaults.

    Mirrors the _required() pattern from observation_publisher.py and
    VM102/config/settings.py (Phase 85 Plan 01).
    """
    v = os.environ.get(key)
    if v is None:
        raise RuntimeError(
            f"Required env var {key!r} not set — fail-fast "
            f"(env-driven-no-fallbacks lock, Phase 85)"
        )
    return v


# ─────────────────────────────────────────────────────────────────────────────
# Connection factories
# ─────────────────────────────────────────────────────────────────────────────

def get_analytics_conn():
    """Return a psycopg2 connection to tradetracker_analytics.

    Reads POSTGRES_HOST, POSTGRES_ANALYTICS_DB, POSTGRES_USER, POSTGRES_PASSWORD
    via _required() — raises RuntimeError on any missing var. No fallback defaults.

    Plan 85-02 imports this for B1 row writes to tradetracker_analytics.
    POSTGRES_PORT has a compose-default (5432) and is not an identity-critical var,
    so it is handled with os.environ.get with an explicit default of "5432".
    Caller manages commit/close — no pooling.
    """
    return psycopg2.connect(
        host=_required("POSTGRES_HOST"),
        dbname=_required("POSTGRES_ANALYTICS_DB"),
        user=_required("POSTGRES_USER"),
        password=_required("POSTGRES_PASSWORD"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
    )


def get_default_conn():
    """Return a psycopg2 connection to the main tradetracker DB (NOT analytics).

    Used by Plan 85-09 to UPDATE economic_event.ai_executive_summary,
    and by any other Phase 85 code that needs to read/write tables in
    tradetracker (e.g. economic_event, ref_economic_indicators).

    Reads POSTGRES_DB (NOT POSTGRES_ANALYTICS_DB) — using get_analytics_conn()
    for tradetracker tables would silently match 0 rows (wrong DB).
    Same fail-fast pattern — no fallback defaults.
    Caller manages commit/close — no pooling.
    """
    return psycopg2.connect(
        host=_required("POSTGRES_HOST"),
        dbname=_required("POSTGRES_DB"),
        user=_required("POSTGRES_USER"),
        password=_required("POSTGRES_PASSWORD"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
    )
