"""Phase 155 D-01a — PillarSnapshotFetcher boundary-validate + no-strip (RED until 155-02).

Target (built in 155-02): ``agents.macro_ask_executor.pillar_fetcher.PillarSnapshotFetcher`` —
a sync httpx read of the blessed VM100 dashboard path that validates the live per-pillar body
into the frozen ``Pillar`` contract WITHOUT stripping fields, mirroring the DomainSnapshotFetcher
branch-map (200→validate / 404→None / 503→None / null→None / 5xx→raise) and the T-155-01
no-JWT-leak invariant.

This whole module is RED by import (the target does not exist yet); it names the exact 155-02
target it will turn GREEN.
"""
from __future__ import annotations

import logging

import httpx
import pytest

# RED-on-target: not built until 155-02. Import failure here IS the Wave-0 signal.
from agents.macro_ask_executor.pillar_fetcher import PillarSnapshotFetcher

_JWT = "eyJHDR.eyJPAYLOAD-secret-do-not-leak.SIG"


def _dashboard_body(pillar_name: str, pillar_dump: dict | None) -> dict:
    """The blessed VM100 dashboard shape: sections.pillars.pillars.<Name> = <Pillar dump | null>."""
    return {"sections": {"pillars": {"pillars": {pillar_name: pillar_dump}}}}


def _transport(status_code: int, body: dict | None):
    def _handler(request: httpx.Request) -> httpx.Response:
        if body is None:
            return httpx.Response(status_code)
        return httpx.Response(status_code, json=body)

    return httpx.MockTransport(_handler)


def test_get_growth_returns_pillar_no_strip(pillar_factory, monkeypatch):
    """200 with a full Pillar dump round-trips into a frozen Pillar — every field preserved."""
    dump = pillar_factory("Growth").model_dump()
    fetcher = PillarSnapshotFetcher(base_url="http://vm100.test", jwt=_JWT)
    monkeypatch.setattr(
        fetcher, "_client", httpx.Client(transport=_transport(200, _dashboard_body("Growth", dump)))
    )
    pillar = fetcher.get("Growth")
    assert pillar is not None
    assert pillar.name == "Growth"
    # NO field stripping: contributors/sparkline/provenance survive the boundary validate.
    assert pillar.contributors == dump["contributors"]
    assert len(pillar.sparkline_90d) == 90
    assert set(pillar.momentum.keys()) == {"1m", "3m", "12m"}


def test_get_404_returns_none(monkeypatch):
    fetcher = PillarSnapshotFetcher(base_url="http://vm100.test", jwt=_JWT)
    monkeypatch.setattr(fetcher, "_client", httpx.Client(transport=_transport(404, None)))
    assert fetcher.get("Growth") is None


def test_get_503_returns_none(monkeypatch):
    fetcher = PillarSnapshotFetcher(base_url="http://vm100.test", jwt=_JWT)
    monkeypatch.setattr(fetcher, "_client", httpx.Client(transport=_transport(503, None)))
    assert fetcher.get("Growth") is None


def test_get_null_pillar_value_returns_none(monkeypatch):
    """A present-but-null per-pillar value (snapshot not ready) → None, never a fabricated Pillar."""
    fetcher = PillarSnapshotFetcher(base_url="http://vm100.test", jwt=_JWT)
    monkeypatch.setattr(
        fetcher, "_client", httpx.Client(transport=_transport(200, _dashboard_body("Growth", None)))
    )
    assert fetcher.get("Growth") is None


def test_get_500_raises(monkeypatch):
    """5xx is loud (raise_for_status) — the executor must see the fault, not a silent None."""
    fetcher = PillarSnapshotFetcher(base_url="http://vm100.test", jwt=_JWT)
    monkeypatch.setattr(fetcher, "_client", httpx.Client(transport=_transport(500, None)))
    with pytest.raises(httpx.HTTPStatusError):
        fetcher.get("Growth")


def test_jwt_never_leaks_in_logs(pillar_factory, monkeypatch, caplog):
    """T-155-01: the bearer JWT must never appear in any captured log/diagnostic line."""
    dump = pillar_factory("Inflation").model_dump()
    fetcher = PillarSnapshotFetcher(base_url="http://vm100.test", jwt=_JWT)
    monkeypatch.setattr(
        fetcher, "_client", httpx.Client(transport=_transport(200, _dashboard_body("Inflation", dump)))
    )
    with caplog.at_level(logging.DEBUG):
        fetcher.get("Inflation")
    assert _JWT not in caplog.text
