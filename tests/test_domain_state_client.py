"""Phase 168 Plan 02 — contract test for ``VM102Client.get_domain_state``.

Exercises the typed DomainState read method against a FAKE HTTP-transport seam:
the client's underlying ``httpx.AsyncClient`` (``client._client``) is swapped for
a stub that records the ``GET`` params and returns canned ``{status, data, meta}``
envelopes. No business logic is mocked — injection is at the transport boundary
only, so the assertions prove the *real* method behaviour:

  * current-only read returns ``data.current`` (``data.previous`` is None),
  * ``previous=True`` retrieves current AND previous in a single call,
  * ``knowledge_time`` is forwarded as a query param (point-in-time threadable),
  * the call targets the typed ``api/v1/domain-state/`` endpoint (G10 — the
    client speaks HTTP only; it never touches ``compute_domain`` / a raw store).

Host-clean: uses the ``fingpt_core`` on the VM107 test path (the Dagster
canonical copy, per conftest) + stdlib ``asyncio`` — no live VM102.
"""

from __future__ import annotations

import asyncio

import pytest


class _FakeResponse:
    """Minimal stand-in for an ``httpx.Response``."""

    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):  # noqa: D401 — httpx surface
        return None

    def json(self) -> dict:
        return self._payload


class _FakeTransport:
    """Records GET calls and returns a canned envelope keyed on ``previous``.

    Replaces ``VM102Client._client`` (the ``httpx.AsyncClient``) AFTER the real
    client is constructed, so no ``headers`` attribute is needed here.
    """

    def __init__(self):
        self.calls: list[dict] = []

    async def get(self, url, params=None):
        recorded = {"url": url, "params": dict(params or {})}
        self.calls.append(recorded)
        prev = recorded["params"].get("previous")
        want_previous = prev in (True, "true", "True", 1, "1")
        current = {"domain_id": "monetary_policy", "current_state": "Stable"}
        if want_previous:
            return _FakeResponse(
                {
                    "status": "ok",
                    "data": {
                        "current": current,
                        "previous": {
                            "domain_id": "monetary_policy",
                            "current_state": "Slowing",
                        },
                    },
                    "meta": {
                        "state_version": "US:monetary_policy:current",
                        "previous_state_version": "US:monetary_policy:previous",
                        "latest_only": True,
                        "as_of_honored": False,
                    },
                }
            )
        return _FakeResponse(
            {
                "status": "ok",
                "data": {"current": current, "previous": None},
                "meta": {
                    "state_version": "US:monetary_policy:current",
                    "previous_state_version": None,
                    "latest_only": True,
                    "as_of_honored": True,
                },
            }
        )


@pytest.fixture()
def client_and_transport(monkeypatch):
    """Construct a real ``VM102Client`` and swap in the fake transport seam."""
    monkeypatch.setenv("VM102_API_URL", "http://vm102-test:8000")
    monkeypatch.setenv("VM102_SERVICE_JWT", "test-service-jwt")

    from fingpt_core.clients.vm102_client import VM102Client

    client = VM102Client()
    transport = _FakeTransport()
    client._client = transport  # inject at the HTTP-transport seam
    return client, transport


def test_get_domain_state_current_only(client_and_transport):
    """A bare call returns current state; previous is None; endpoint is typed."""
    client, transport = client_and_transport

    res = asyncio.run(client.get_domain_state("US", "monetary_policy"))

    assert res["status"] == "ok"
    assert res["data"]["current"]["domain_id"] == "monetary_policy"
    assert res["data"]["previous"] is None

    # G10 — the method spoke HTTP to the typed domain-state endpoint only.
    assert len(transport.calls) == 1
    assert "domain-state" in transport.calls[0]["url"]
    # previous defaults to False and is forwarded so the endpoint can branch.
    assert transport.calls[0]["params"].get("previous") in (False, "false", 0)
    # No knowledge_time param when none supplied.
    assert "knowledge_time" not in transport.calls[0]["params"]


def test_get_domain_state_current_and_previous(client_and_transport):
    """``previous=True`` retrieves current AND previous in a single typed call."""
    client, transport = client_and_transport

    res = asyncio.run(
        client.get_domain_state("US", "monetary_policy", previous=True)
    )

    assert res["data"]["current"]["current_state"] == "Stable"
    assert res["data"]["previous"] is not None
    assert res["data"]["previous"]["current_state"] == "Slowing"
    assert res["meta"]["previous_state_version"] == "US:monetary_policy:previous"
    assert transport.calls[0]["params"].get("previous") in (True, "true", 1)


def test_get_domain_state_forwards_knowledge_time(client_and_transport):
    """``knowledge_time`` is forwarded as a query param (point-in-time honesty)."""
    client, transport = client_and_transport

    kt = "2026-01-01T00:00:00Z"
    asyncio.run(
        client.get_domain_state("US", "monetary_policy", knowledge_time=kt)
    )

    assert transport.calls[0]["params"].get("knowledge_time") == kt
