"""Phase 156 — DomainSnapshotFetcher tests (D-04 tier-1 CI integration + error modes).

Fake-httpx CI integration test (no live VM100/JWT) proving the full
MACRO_RELEASE -> fetcher -> analyst -> SpecialistResponse path fires on a real,
validated ``Domain`` (AZE-02 acceptance). Plus error-mode unit tests covering
the D-02 branch map: unknown-slug drop (no HTTP call), 404 transient miss
(returns None, retry-friendly), hard/net error raises, and the JWT bearer
header.

HTTP-mock idiom mirrors ``tests/phase83/test_macro_calendar_client.py``.
The ``Domain`` fixture is the ready-made contract-faithful ``_fake_domain``
builder from ``tests/agents/test_domain_analyst_contract.py`` — do NOT hand-roll
a Domain (frozen + extra="forbid").
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from agents.domain_analyst_subscriber.domain_fetcher import DomainSnapshotFetcher
from agents.domain_analyst_subscriber.subscriber import (
    DomainAnalystSubscriber,
    load_analysts,
)
from contracts.economic_intelligence.domain import Domain
from contracts.economic_intelligence.events import (
    EconomicEvent,
    EventSeverity,
    EventType,
)
from contracts.economic_intelligence.specialist_response import SpecialistResponse

# Contract-faithful Domain builder (all 12 slugs) — reuse, never hand-roll.
from tests.agents.test_domain_analyst_contract import _fake_domain


_JWT = "test-service-jwt"


def _event(
    *,
    event_id: str = "evt-1",
    affected_domains: list[str] | None = None,
    snapshot_version: int = 1,
    country: str = "US",
) -> EconomicEvent:
    payload: dict = {"snapshot_version": snapshot_version}
    if affected_domains is not None:
        payload["affected_domains"] = affected_domains
    return EconomicEvent(
        event_id=event_id,
        event_type=EventType.MACRO_RELEASE,
        severity=EventSeverity.MEDIUM,
        country=country,
        occurred_at=datetime.now(tz=timezone.utc),
        source="vm101.economic_event",
        payload=payload,
    )


def _make_fetcher(jwt: str = _JWT) -> DomainSnapshotFetcher:
    return DomainSnapshotFetcher(
        base_url="http://vm100:8000", jwt=jwt, timeout_sec=2.0
    )


def _ok_response(slug: str) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = _fake_domain(slug).model_dump(mode="json")
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# D-04 tier-1 CI integration: release -> fetcher -> analyst emits SpecialistResponse
# ---------------------------------------------------------------------------


def test_release_fires_analyst_with_real_domain():
    """Fake-httpx MACRO_RELEASE end-to-end: the inflation analyst emits a
    SpecialistResponse backed by a real, validated Domain."""
    analysts = load_analysts()

    # Spy on the real inflation analyst's invoke — call through, capture output.
    real_invoke = analysts["inflation"].invoke
    captured: dict = {}

    def _spy(domain, context=None):
        resp = real_invoke(domain, context)
        captured["resp"] = resp
        return resp

    analysts["inflation"].invoke = _spy

    with patch("httpx.get", return_value=_ok_response("inflation")):
        fetcher = _make_fetcher()
        sub = DomainAnalystSubscriber(analysts=analysts, domain_fetcher=fetcher)
        sub.handle(_event(affected_domains=["inflation"]))

    assert "resp" in captured, "inflation analyst was never invoked"
    assert isinstance(captured["resp"], SpecialistResponse)


# ---------------------------------------------------------------------------
# Fetcher returns a validated Domain on 200
# ---------------------------------------------------------------------------


def test_returns_validated_domain():
    with patch("httpx.get", return_value=_ok_response("growth")):
        fetcher = _make_fetcher()
        result = fetcher("growth", _event(affected_domains=["growth"]))
    assert isinstance(result, Domain)
    assert result.slug == "growth"


# ---------------------------------------------------------------------------
# 404 transient miss -> None, no raise (retry-friendly)
# ---------------------------------------------------------------------------


def test_transient_404_returns_none():
    resp = MagicMock()
    resp.status_code = 404
    resp.raise_for_status = MagicMock()
    with patch("httpx.get", return_value=resp):
        fetcher = _make_fetcher()
        result = fetcher("growth", _event(affected_domains=["growth"]))
    assert result is None
    resp.raise_for_status.assert_not_called()


# ---------------------------------------------------------------------------
# Unknown slug -> warning + None, NO http call
# ---------------------------------------------------------------------------


def test_unknown_slug_drops_with_warning(caplog):
    fetcher = _make_fetcher()
    with patch("httpx.get") as mock_get:
        with caplog.at_level(logging.WARNING):
            result = fetcher("not_a_real_domain", _event())
    assert result is None
    mock_get.assert_not_called()
    assert any(
        "unknown slug" in rec.getMessage().lower() for rec in caplog.records
    ), "expected a warning-level log naming the unknown slug"


# ---------------------------------------------------------------------------
# Hard HTTP error (raise_for_status) and net error (ConnectError) both raise
# ---------------------------------------------------------------------------


def test_hard_error_raises():
    # 5xx via raise_for_status -> propagates loudly (routes to subscriber no-mark).
    resp = MagicMock()
    resp.status_code = 500
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=MagicMock(), response=resp
    )
    with patch("httpx.get", return_value=resp):
        fetcher = _make_fetcher()
        with pytest.raises(httpx.HTTPStatusError):
            fetcher("growth", _event(affected_domains=["growth"]))

    # Network/timeout error -> re-raised as a distinct transient RuntimeError.
    with patch("httpx.get", side_effect=httpx.ConnectError("connection refused")):
        fetcher = _make_fetcher()
        with pytest.raises(RuntimeError):
            fetcher("growth", _event(affected_domains=["growth"]))


# ---------------------------------------------------------------------------
# JWT bearer header is sent with the real token (never a default/placeholder)
# ---------------------------------------------------------------------------


def test_jwt_header_sent_never_default():
    with patch("httpx.get", return_value=_ok_response("growth")) as mock_get:
        fetcher = _make_fetcher(jwt="my-real-service-jwt")
        fetcher("growth", _event(affected_domains=["growth"]))
    headers = mock_get.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer my-real-service-jwt"
