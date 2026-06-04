"""Phase 83 Plan 09 Task 1 — MacroCalendarHTTPClient test suite.

Tests for VM107/services/macro_calendar_client.py.

Auth model (per 83-07 SUMMARY):
  - GET /api/v1/mission-control/calendar/upcoming?hours=N
  - Authorization: Bearer <VM107_SERVICE_JWT>
  - Returns 200 {"items": [...], ...} or 401

Env-driven config lock (CLAUDE.md):
  - MACRO_EMITTER_CALENDAR_URL — required, no default
  - VM107_SERVICE_JWT — required, no default
  - MACRO_EMITTER_CALENDAR_TIMEOUT_SEC — optional, defaults to 5

RISK-06 consumer closure: client must not import Django ORM or mount VM100 filesystem.
"""
import importlib
import sys
import os
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(base_url="http://vm100:8000", jwt="test-jwt-token", timeout=2.0):
    """Build a MacroCalendarHTTPClient with explicit constructor args (bypass env)."""
    from services.macro_calendar_client import MacroCalendarHTTPClient
    return MacroCalendarHTTPClient(base_url=base_url, jwt=jwt, timeout_sec=timeout)


# ---------------------------------------------------------------------------
# Test 1: successful 200 response returns item list
# ---------------------------------------------------------------------------

@pytest.mark.phase83
def test_fetch_upcoming_returns_items_on_200():
    """Client returns item list on HTTP 200 response."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "items": [
            {"event_id": "1", "indicator_code": "CPI", "indicator_short_name": "CPI",
             "event_date": "2026-06-05T12:00:00Z", "severity": "HIGH",
             "releasing_authority": "BLS", "affected_symbols": [], "reference_period_date": None},
            {"event_id": "2", "indicator_code": "GDP", "indicator_short_name": "GDP",
             "event_date": "2026-06-06T12:00:00Z", "severity": "CRITICAL",
             "releasing_authority": "BEA", "affected_symbols": [], "reference_period_date": None},
        ],
        "generated_at": "2026-06-04T05:00:00Z",
        "source": "vm100.calendar",
        "hours_window": 24,
    }
    mock_resp.raise_for_status = MagicMock()  # no exception

    with patch("httpx.get", return_value=mock_resp) as mock_get:
        client = _make_client()
        result = client.fetch_upcoming(hours=24)

    assert len(result) == 2
    assert result[0]["event_id"] == "1"
    assert result[1]["indicator_code"] == "GDP"


# ---------------------------------------------------------------------------
# Test 2: HTTP 500 response returns empty list (no exception)
# ---------------------------------------------------------------------------

@pytest.mark.phase83
def test_fetch_upcoming_returns_empty_on_500():
    """Client logs warning and returns [] on HTTP 500 — composer handles degradation."""
    import httpx

    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=MagicMock(), response=mock_resp
    )

    with patch("httpx.get", return_value=mock_resp):
        client = _make_client()
        result = client.fetch_upcoming(hours=24)

    assert result == []


# ---------------------------------------------------------------------------
# Test 3: ConnectError returns empty list (no exception)
# ---------------------------------------------------------------------------

@pytest.mark.phase83
def test_fetch_upcoming_returns_empty_on_connect_refused():
    """Client returns [] on ConnectError — composer falls through to Tier-1 degradation."""
    import httpx

    with patch("httpx.get", side_effect=httpx.ConnectError("Connection refused")):
        client = _make_client()
        result = client.fetch_upcoming(hours=24)

    assert result == []


# ---------------------------------------------------------------------------
# Test 4: JWT in Authorization header
# ---------------------------------------------------------------------------

@pytest.mark.phase83
def test_passes_jwt_in_authorization_header():
    """Client sends Authorization: Bearer <jwt> header on every request."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"items": []}
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=mock_resp) as mock_get:
        client = _make_client(jwt="my-service-jwt-token")
        client.fetch_upcoming(hours=24)

    call_kwargs = mock_get.call_args
    headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers") or call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {}
    # Handle both positional and keyword args
    if not headers and mock_get.call_args:
        all_kwargs = mock_get.call_args[1] if mock_get.call_args[1] else {}
        if not all_kwargs and mock_get.call_args[0]:
            # positional — not likely
            pass
        headers = all_kwargs.get("headers", {})

    assert "Authorization" in headers
    assert headers["Authorization"] == "Bearer my-service-jwt-token"


# ---------------------------------------------------------------------------
# Test 5: hours query param is forwarded
# ---------------------------------------------------------------------------

@pytest.mark.phase83
def test_passes_hours_query_param():
    """Client passes hours=N as query parameter to the endpoint."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"items": []}
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.get", return_value=mock_resp) as mock_get:
        client = _make_client()
        client.fetch_upcoming(hours=48)

    call_kwargs = mock_get.call_args
    params = call_kwargs.kwargs.get("params") or {}
    assert params.get("hours") == 48


# ---------------------------------------------------------------------------
# Test 6: fail-fast on missing MACRO_EMITTER_CALENDAR_URL env var
# ---------------------------------------------------------------------------

@pytest.mark.phase83
def test_fail_fast_on_missing_env_var():
    """Client module raises KeyError at import if MACRO_EMITTER_CALENDAR_URL is not set.

    Per CLAUDE.md env-driven-config lock: no os.getenv defaults for required vars.
    Fail-fast at import/startup beats silent misconfiguration.
    """
    # Save and remove env vars
    saved_url = os.environ.pop("MACRO_EMITTER_CALENDAR_URL", None)
    saved_jwt = os.environ.pop("VM107_SERVICE_JWT", None)

    # Remove cached module so reimport runs module-level code
    for key in list(sys.modules.keys()):
        if "macro_calendar_client" in key:
            del sys.modules[key]

    try:
        with pytest.raises(KeyError):
            import services.macro_calendar_client  # noqa: F401
    finally:
        # Restore env vars
        if saved_url is not None:
            os.environ["MACRO_EMITTER_CALENDAR_URL"] = saved_url
        if saved_jwt is not None:
            os.environ["VM107_SERVICE_JWT"] = saved_jwt
        # Remove the potentially-failed module from cache
        for key in list(sys.modules.keys()):
            if "macro_calendar_client" in key:
                del sys.modules[key]
