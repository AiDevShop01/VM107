"""Phase 168 Plan 05 Task 1 — EvidencePackAssembler tier-degradation pillars.

Proves the D-02 (no-brick) + D-07 (tier-declared degradation) contract of the
`EvidencePackAssembler`:

  * the fixed 7-facet ASSEMBLY_ORDER is the canonical composition order,
  * a boot invariant fails fast when ASSEMBLY_ORDER does not cover the
    DomainEvidencePack facet set (tampered-order raise),
  * a facet composer that RAISES never bricks the pack — the exception is
    converted to a typed PROVIDER_FAILURE manifest entry (T-168-13),
  * a REQUIRED facet down => pack_outcome "degraded" + the pack records the
    agent must abstain (STATE_STALE for domain_state / INSUFFICIENT_EVIDENCE for
    state_diff),
  * an ENRICHMENT facet (contradiction) down => facet omitted + reason recorded,
    pack NOT degraded,
  * the full DomainEvidencePack shape (every facet named in the manifest) is
    ALWAYS present even under degradation (D-03).

Host-clean: fingpt_core contract (canonical Dagster copy via conftest) +
`core.evidence.assembler` / `core.evidence.tiers` (pure — pydantic + stdlib). No
live VM102 / Postgres — facet composers are injected fakes at the seam.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from fingpt_core.contracts.evidence_pack import (
    ContradictionFacet,
    ContributorFacet,
    DomainEvidencePack,
    DomainStateFacet,
    FacetIntegrity,
    StateDiffFacet,
)

from core.evidence import assembler as A
from core.evidence import tiers as T

_KT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _req() -> "A.AssemblyRequest":
    return A.AssemblyRequest(country="US", domain_slug="monetary_policy", knowledge_time=_KT)


def _ok(name, value):
    def _c(ctx):
        return T.FacetOutcome(name=name, ok=True, integrity=FacetIntegrity.NEUTRAL, reason=None, value=value)

    return _c


def _fail(name, integrity=FacetIntegrity.UNAVAILABLE, reason="down"):
    def _c(ctx):
        return T.FacetOutcome(name=name, ok=False, integrity=integrity, reason=reason, value=None)

    return _c


def _raises(name):
    def _c(ctx):
        raise RuntimeError(f"boom in {name}")

    return _c


def _healthy_reuse_composers() -> dict:
    """The 4 reuse/typed facets wired healthy; the 3 net-new facets
    (signal_importance/historical_context/prior_assessment) stay on the
    assembler's deferred-placeholder defaults (pending 168-06)."""

    def _ds(ctx):
        ctx.scratch["previous_state"] = DomainStateFacet(state_version="US:mp:v0", label="Easing")
        return T.FacetOutcome(
            name="domain_state",
            ok=True,
            integrity=FacetIntegrity.NEUTRAL,
            reason=None,
            value=DomainStateFacet(state_version="US:mp:v1", label="Stable", score=0.1, confidence=0.8),
        )

    return {
        "domain_state": _ds,
        "state_diff": _ok(
            "state_diff",
            StateDiffFacet(changed=True, previous_label="Easing", current_label="Stable", delta_score=0.2),
        ),
        "contribution": _ok("contribution", (ContributorFacet(name="CPI", contribution=0.4, confidence=0.7),)),
        "contradiction": _ok("contradiction", (ContradictionFacet(claim_a="hawkish", claim_b="dovish", severity=0.5),)),
    }


def _manifest_reasons(pack: DomainEvidencePack) -> str:
    return " ".join(f.reason or "" for f in pack.pack_integrity.facets)


def _records(pack: DomainEvidencePack) -> dict:
    return {f.facet: f for f in pack.pack_integrity.facets}


# ---------------------------------------------------------------------------
# ASSEMBLY_ORDER + boot invariant
# ---------------------------------------------------------------------------


def test_assembly_order_is_the_fixed_canonical_seven():
    assert A.ASSEMBLY_ORDER == [
        "domain_state",
        "state_diff",
        "contribution",
        "signal_importance",
        "contradiction",
        "historical_context",
        "prior_assessment",
    ]


def test_boot_invariant_raises_on_tampered_order():
    tampered = [f for f in A.ASSEMBLY_ORDER if f != "prior_assessment"]
    with pytest.raises(RuntimeError):
        A.EvidencePackAssembler(assembly_order=tampered)


def test_boot_invariant_raises_on_unknown_facet():
    tampered = list(A.ASSEMBLY_ORDER[:-1]) + ["not_a_real_facet"]
    with pytest.raises(RuntimeError):
        A.EvidencePackAssembler(assembly_order=tampered)


# ---------------------------------------------------------------------------
# D-02 no-brick — a raising facet never propagates
# ---------------------------------------------------------------------------


def test_raising_facet_does_not_brick_the_pack():
    comps = _healthy_reuse_composers()
    comps["contribution"] = _raises("contribution")
    pack = A.EvidencePackAssembler(composers=comps).assemble(_req())  # must NOT raise
    assert isinstance(pack, DomainEvidencePack)
    rec = _records(pack)["contribution"]
    assert rec.integrity == FacetIntegrity.PROVIDER_FAILURE
    assert rec.reason  # carries WHY, never silently empty


# ---------------------------------------------------------------------------
# D-07 REQUIRED down => degraded + abstain code
# ---------------------------------------------------------------------------


def test_required_domain_state_down_degrades_and_abstains_state_stale():
    comps = _healthy_reuse_composers()
    comps["domain_state"] = _fail("domain_state", FacetIntegrity.UNAVAILABLE)
    pack = A.EvidencePackAssembler(composers=comps).assemble(_req())
    assert pack.pack_integrity.pack_outcome == "degraded"
    assert "STATE_STALE" in _manifest_reasons(pack)
    # the shape is still fully present (D-03) — a degraded DomainStateFacet, not a crash.
    assert isinstance(pack.domain_state, DomainStateFacet)
    assert pack.domain_state.integrity == FacetIntegrity.UNAVAILABLE


def test_required_state_diff_down_degrades_with_insufficient_evidence():
    comps = _healthy_reuse_composers()
    comps["state_diff"] = _fail("state_diff", FacetIntegrity.UNAVAILABLE)
    pack = A.EvidencePackAssembler(composers=comps).assemble(_req())
    assert pack.pack_integrity.pack_outcome == "degraded"
    assert "INSUFFICIENT_EVIDENCE" in _manifest_reasons(pack)


# ---------------------------------------------------------------------------
# D-07 ENRICHMENT down => omit + reason, NOT degraded
# ---------------------------------------------------------------------------


def test_enrichment_contradiction_down_is_omitted_not_degraded():
    comps = _healthy_reuse_composers()
    comps["contradiction"] = _fail("contradiction", FacetIntegrity.UNAVAILABLE, reason="engine down")
    pack = A.EvidencePackAssembler(composers=comps).assemble(_req())
    assert pack.contradictions == ()  # omitted
    assert pack.pack_integrity.pack_outcome != "degraded"  # enrichment never sinks the pack
    assert _records(pack)["contradiction"].reason  # honest-empty: carries WHY


# ---------------------------------------------------------------------------
# D-03 full shape always present + manifest lists every facet
# ---------------------------------------------------------------------------


def test_full_shape_and_per_facet_manifest_always_present():
    pack = A.EvidencePackAssembler(composers=_healthy_reuse_composers()).assemble(_req())
    assert {f.facet for f in pack.pack_integrity.facets} == set(A.ASSEMBLY_ORDER)
    # healthy reuse facets populated; deferred net-new facets recorded (pending 168-06)
    assert pack.pack_integrity.pack_outcome == "success"
    deferred = _records(pack)["signal_importance"]
    assert deferred.reason and "168-06" in deferred.reason
