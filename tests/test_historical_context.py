"""Phase 168 Plan 06 Task 2 — HistoricalContext facet (percentile + analogue de-stub).

Proves the ENRICHMENT HistoricalContext facet (D-01/D-02/D-07):

  * the VM102 percentile sub-path always populates ``historical_percentile`` when
    the typed reader returns data,
  * the analogue sub-path (VM105 Neo4j via ``query_analogues``) is attempted ONLY
    when ``VM105_NEO4J_URL`` is set; when unset OR unreachable the analogue
    sub-facet is omitted with a recorded reason — the ``NotImplementedError`` /
    connection error NEVER propagates (the assembler does not raise),
  * percentile still serves HistoricalContext even when the analogue path omits,
  * no percentile reader => ENRICHMENT omit-with-reason (non-downgrading).

Host-clean: fingpt_core contract + core.evidence.* (pydantic + stdlib). VM102 /
VM105 are injected fakes / patched seams — no live services.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fingpt_core.contracts.evidence_pack import (
    DomainEvidencePack,
    DomainStateFacet,
    FacetIntegrity,
    HistoricalPercentileFacet,
    StateDiffFacet,
)

from core.counterfactual import analogue_retrieval
from core.evidence import assembler as A
from core.evidence import tiers as T
from core.evidence.facets import historical_context as hc_mod

_NOW = datetime.now(timezone.utc)


def _healthy_required_composers() -> dict:
    """Wire the 2 REQUIRED reuse facets healthy so an ENRICHMENT facet is isolated
    (unwired REQUIRED facets would dominate the pack as ``degraded``)."""

    def _ds(ctx):
        return T.FacetOutcome(
            name="domain_state",
            ok=True,
            integrity=FacetIntegrity.NEUTRAL,
            value=DomainStateFacet(state_version="US:inf:v1", label="Cooling", score=0.1),
        )

    def _sd(ctx):
        return T.FacetOutcome(
            name="state_diff",
            ok=True,
            integrity=FacetIntegrity.NEUTRAL,
            value=StateDiffFacet(changed=False, current_label="Cooling"),
        )

    return {"domain_state": _ds, "state_diff": _sd}


class _FakePercentileReader:
    def __init__(self, result):
        self._result = result

    def historical_percentile(self, country, domain_slug, *, knowledge_time=None):
        return self._result


_PCT = {"percentile": 72.5, "window": "10y", "n_observations": 120, "indicator": "CPIAUCSL", "surprise": -0.3}


def _req(knowledge_time=_NOW) -> A.AssemblyRequest:
    return A.AssemblyRequest(country="US", domain_slug="inflation", knowledge_time=knowledge_time)


def _ctx(reader) -> A.AssemblyContext:
    return A.AssemblyContext(request=_req(), deps=A.FacetDeps(percentile_reader=reader))


def _records(pack: DomainEvidencePack) -> dict:
    return {f.facet: f for f in pack.pack_integrity.facets}


# ---------------------------------------------------------------------------
# Percentile sub-path always serves; analogue omitted when VM105 unset
# ---------------------------------------------------------------------------


def test_percentile_serves_and_analogue_omitted_when_vm105_unset(monkeypatch):
    monkeypatch.delenv("VM105_NEO4J_URL", raising=False)
    out = hc_mod.compose_historical_context(_ctx(_FakePercentileReader(_PCT)))
    assert out.ok is True
    assert isinstance(out.value, HistoricalPercentileFacet)
    assert out.value.percentile == 72.5
    assert out.value.window == "10y"
    # analogue sub-facet omitted honestly (recorded reason), never raised
    assert out.reason and "analogue" in out.reason.lower()


def test_analogue_connection_error_is_caught_percentile_still_serves(monkeypatch):
    monkeypatch.setenv("VM105_NEO4J_URL", "http://vm105.invalid:7474")

    def _boom(*a, **k):
        raise ConnectionError("VM105 Neo4j unreachable in dev")

    monkeypatch.setattr(analogue_retrieval, "_call_neo4j_query_analogues", _boom)
    out = hc_mod.compose_historical_context(_ctx(_FakePercentileReader(_PCT)))  # must NOT raise
    assert out.ok is True
    assert isinstance(out.value, HistoricalPercentileFacet)
    assert out.reason and "analogue" in out.reason.lower()


def test_analogue_success_records_count(monkeypatch):
    monkeypatch.setenv("VM105_NEO4J_URL", "http://vm105.invalid:7474")
    rows = [
        {"release_id": f"r{i}", "release_date": "2020-01-0{}".format(i + 1), "indicator_surprise": -0.3, "regime_at_time": "risk_off"}
        for i in range(5)
    ]
    monkeypatch.setattr(analogue_retrieval, "_call_neo4j_query_analogues", lambda *a, **k: rows)
    out = hc_mod.compose_historical_context(_ctx(_FakePercentileReader(_PCT)))
    assert out.ok is True
    assert out.reason and "5" in out.reason  # analogue count recorded


# ---------------------------------------------------------------------------
# No percentile reader => ENRICHMENT omit, non-downgrading
# ---------------------------------------------------------------------------


def test_no_percentile_reader_omits_with_reason(monkeypatch):
    monkeypatch.delenv("VM105_NEO4J_URL", raising=False)
    out = hc_mod.compose_historical_context(A.AssemblyContext(request=_req(), deps=A.FacetDeps()))
    assert out.ok is False
    assert out.reason


def test_no_percentile_data_omits_with_reason(monkeypatch):
    monkeypatch.delenv("VM105_NEO4J_URL", raising=False)
    out = hc_mod.compose_historical_context(_ctx(_FakePercentileReader(None)))
    assert out.ok is False
    assert out.reason


# ---------------------------------------------------------------------------
# Wired into the assembler => populates historical_percentile, never bricks
# ---------------------------------------------------------------------------


def test_registered_populates_historical_percentile(monkeypatch):
    monkeypatch.delenv("VM105_NEO4J_URL", raising=False)
    deps = A.FacetDeps(percentile_reader=_FakePercentileReader(_PCT))
    assembler = A.EvidencePackAssembler(composers=_healthy_required_composers())
    pack = assembler.assemble(_req(), deps=deps)  # must NOT raise
    assert isinstance(pack.historical_percentile, HistoricalPercentileFacet)
    assert pack.historical_percentile.percentile == 72.5
    assert pack.pack_integrity.pack_outcome != "degraded"
