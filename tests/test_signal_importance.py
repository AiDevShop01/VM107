"""Phase 168 Plan 06 Task 1 — SignalImportance facet (top_k + excluded, IMPORTANT).

Proves the NET-NEW SignalImportance compute (D-01) is real, deterministic, and
IMPORTANT-tier degrade-graceful (D-02):

  * ranks candidate signals into a bounded ``top_k`` AND an ``excluded`` set,
    each excluded signal carrying a reason — a frozen struct, never a series,
  * deterministic ordering: same inputs -> identical top_k + excluded ordering,
  * missing inputs (seam present but no data) => a typed FacetIntegrity failure +
    warning (pack ``partial``, IMPORTANT tier) — the assembler NEVER raises,
  * wired into the assembler's ``signal_importance`` slot (real, not deferred)
    when the seam is supplied.

Host-clean: fingpt_core contract + core.evidence.* (pydantic + stdlib). The
candidate-signal data source is an injected FAKE seam — no live VM102.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone

from fingpt_core.contracts.evidence_pack import DomainEvidencePack, FacetIntegrity, SignalFacet

from core.evidence import assembler as A
from core.evidence.facets import signal_importance as si_mod

_NOW = datetime.now(timezone.utc)

# 7 candidate signals with distinct importances (+ one ineligible) so top_k=5
# splits cleanly into 5 top + 2 excluded (1 by rank, 1 by ineligibility).
_CANDIDATES = [
    {"signal_id": "cpi_yoy", "importance": 0.91},
    {"signal_id": "unemployment", "importance": 0.62},
    {"signal_id": "pmi", "importance": 0.77},
    {"signal_id": "retail_sales", "importance": 0.44},
    {"signal_id": "wages", "importance": 0.55},
    {"signal_id": "housing_starts", "importance": 0.33},
    {"signal_id": "stale_proxy", "importance": 0.99, "eligible": False, "exclude_reason": "stale > 90d"},
]


class _FakeSignalReader:
    def __init__(self, rows):
        self._rows = rows

    def candidate_signals(self, country, domain_slug, *, knowledge_time=None):
        return self._rows


def _req(knowledge_time=_NOW) -> A.AssemblyRequest:
    return A.AssemblyRequest(country="US", domain_slug="inflation", knowledge_time=knowledge_time)


def _deps(rows) -> A.FacetDeps:
    return A.FacetDeps(signal_reader=_FakeSignalReader(rows))


def _records(pack: DomainEvidencePack) -> dict:
    return {f.facet: f for f in pack.pack_integrity.facets}


# ---------------------------------------------------------------------------
# Deterministic top_k + excluded
# ---------------------------------------------------------------------------


def test_deterministic_top_k_and_excluded():
    ctx = A.AssemblyContext(request=_req(), deps=_deps(_CANDIDATES))
    out1 = si_mod.compose_signal_importance(ctx)
    ctx2 = A.AssemblyContext(request=_req(), deps=_deps(list(reversed(_CANDIDATES))))
    out2 = si_mod.compose_signal_importance(ctx2)

    assert out1.ok is True
    top = out1.value["top"]
    excluded = out1.value["excluded"]

    # bounded k (default 5) and everything else excluded
    assert len(top) == si_mod.DEFAULT_TOP_K == 5
    assert all(isinstance(s, SignalFacet) for s in top)
    assert all(isinstance(s, SignalFacet) for s in excluded)

    # top ordered by importance desc — the eligible highest five
    assert [s.signal_id for s in top] == ["cpi_yoy", "pmi", "unemployment", "wages", "retail_sales"]

    # excluded: the lowest-eligible (by rank) + the ineligible (by reason)
    excluded_ids = {s.signal_id for s in excluded}
    assert excluded_ids == {"housing_starts", "stale_proxy"}
    assert all(s.excluded_reason for s in excluded)  # every excluded carries WHY

    # deterministic: input order does not change the ranking
    assert [s.signal_id for s in top] == [s.signal_id for s in out2.value["top"]]
    assert {s.signal_id for s in excluded} == {s.signal_id for s in out2.value["excluded"]}


def test_ineligible_signal_excluded_with_its_reason():
    ctx = A.AssemblyContext(request=_req(), deps=_deps(_CANDIDATES))
    out = si_mod.compose_signal_importance(ctx)
    stale = next(s for s in out.value["excluded"] if s.signal_id == "stale_proxy")
    assert stale.excluded_reason and "stale" in stale.excluded_reason


# ---------------------------------------------------------------------------
# No series/DataFrame in the payload (a struct, never a series)
# ---------------------------------------------------------------------------


def test_payload_is_a_struct_never_a_series():
    src = inspect.getsource(si_mod)
    assert "DataFrame" not in src
    assert "pl.Series" not in src
    ctx = A.AssemblyContext(request=_req(), deps=_deps(_CANDIDATES))
    out = si_mod.compose_signal_importance(ctx)
    assert isinstance(out.value, dict)
    for s in (*out.value["top"], *out.value["excluded"]):
        assert isinstance(s, SignalFacet)


# ---------------------------------------------------------------------------
# IMPORTANT tier: missing inputs => warn (partial), never raise
# ---------------------------------------------------------------------------


def test_missing_inputs_warns_not_raises():
    # seam present but returns None (provider outage) => IMPORTANT down => partial.
    deps = A.FacetDeps(signal_reader=_FakeSignalReader(None))
    pack = A.EvidencePackAssembler().assemble(_req(), deps=deps)  # must NOT raise
    assert isinstance(pack, DomainEvidencePack)
    assert pack.top_signals == ()
    assert pack.pack_integrity.pack_outcome == "partial"
    rec = _records(pack)["signal_importance"]
    assert rec.integrity in (FacetIntegrity.UNAVAILABLE, FacetIntegrity.INSUFFICIENT_HISTORY)
    assert rec.reason  # honest-empty: carries WHY


# ---------------------------------------------------------------------------
# Wired into the assembler's signal_importance slot (real, not deferred)
# ---------------------------------------------------------------------------


def test_registered_and_populates_pack_top_and_excluded_signals():
    pack = A.EvidencePackAssembler().assemble(_req(), deps=_deps(_CANDIDATES))
    assert len(pack.top_signals) == 5
    assert len(pack.excluded_signals) == 2
    assert all(isinstance(s, SignalFacet) for s in pack.top_signals)
    # no longer the 168-05 deferred placeholder
    rec = _records(pack)["signal_importance"]
    assert not (rec.reason and "pending 168-06" in rec.reason)
