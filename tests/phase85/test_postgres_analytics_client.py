"""Phase 85 Plan 01 — psycopg2 analytics DB client tests.

Tests the fail-fast behavior of:
- get_analytics_conn() → tradetracker_analytics
- get_default_conn() → tradetracker

Both must raise RuntimeError with the missing var name when any required
env var is absent. When all vars are set, connections must be live.
"""
import os

import pytest

pytestmark = pytest.mark.phase_85

# Env vars needed for live connection tests
_REQUIRED_VARS = ("POSTGRES_HOST", "POSTGRES_USER", "POSTGRES_PASSWORD")
_ANALYTICS_VAR = "POSTGRES_ANALYTICS_DB"
_DEFAULT_VAR = "POSTGRES_DB"

_all_analytics_vars_set = all(
    os.environ.get(v) for v in (*_REQUIRED_VARS, _ANALYTICS_VAR)
)
_all_default_vars_set = all(
    os.environ.get(v) for v in (*_REQUIRED_VARS, _DEFAULT_VAR)
)


# ─── get_analytics_conn ───────────────────────────────────────────────────────

def test_get_analytics_conn_missing_host(monkeypatch):
    """Missing POSTGRES_HOST → RuntimeError mentioning the var name."""
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    from services.postgres_analytics_client import get_analytics_conn
    with pytest.raises(RuntimeError, match="POSTGRES_HOST"):
        get_analytics_conn()


def test_get_analytics_conn_missing_db(monkeypatch):
    """Missing POSTGRES_ANALYTICS_DB → RuntimeError mentioning the var name.

    Sets POSTGRES_HOST so the first _required() call passes, then removes
    POSTGRES_ANALYTICS_DB so the second _required() raises with the right var name.
    """
    monkeypatch.setenv("POSTGRES_HOST", "192.168.1.151")
    monkeypatch.delenv("POSTGRES_ANALYTICS_DB", raising=False)
    from services.postgres_analytics_client import get_analytics_conn
    with pytest.raises(RuntimeError, match="POSTGRES_ANALYTICS_DB"):
        get_analytics_conn()


@pytest.mark.skipif(
    not _all_analytics_vars_set,
    reason="POSTGRES_* env vars not set — skipping live connection test",
)
def test_get_analytics_conn_real():
    """All env vars set → live connection to tradetracker_analytics works."""
    from services.postgres_analytics_client import get_analytics_conn
    conn = get_analytics_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        result = cur.fetchone()
        assert result == (1,)
    finally:
        conn.close()


# ─── get_default_conn ─────────────────────────────────────────────────────────

def test_get_default_conn_missing_db(monkeypatch):
    """Missing POSTGRES_DB → RuntimeError mentioning the var name.

    Sets POSTGRES_HOST so the first _required() call passes, then removes
    POSTGRES_DB so the second _required() raises with the right var name.
    """
    monkeypatch.setenv("POSTGRES_HOST", "192.168.1.151")
    monkeypatch.delenv("POSTGRES_DB", raising=False)
    from services.postgres_analytics_client import get_default_conn
    with pytest.raises(RuntimeError, match="POSTGRES_DB"):
        get_default_conn()


def test_get_default_conn_missing_host(monkeypatch):
    """Missing POSTGRES_HOST → RuntimeError mentioning the var name."""
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    from services.postgres_analytics_client import get_default_conn
    with pytest.raises(RuntimeError, match="POSTGRES_HOST"):
        get_default_conn()


@pytest.mark.skipif(
    not _all_default_vars_set,
    reason="POSTGRES_* env vars not set — skipping live connection test",
)
def test_get_default_conn_reaches_tradetracker():
    """All env vars set → live connection lands on tradetracker (economic_event exists)."""
    from services.postgres_analytics_client import get_default_conn
    conn = get_default_conn()
    try:
        cur = conn.cursor()
        # Prove the connection is on tradetracker (NOT tradetracker_analytics)
        # by querying economic_event which lives only in tradetracker.
        cur.execute("SELECT COUNT(*) FROM economic_event")
        row = cur.fetchone()
        assert row is not None
        assert row[0] >= 0  # any row count is valid
    finally:
        conn.close()
