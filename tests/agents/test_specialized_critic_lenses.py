"""Phase 170 Plan 03 Task 2 — five deterministic lens rule bundles (incl. SC#2).

Exercises `SpecializedCritic(lens)` over the shared Plan 01 fixtures
(`bare_correlation_assessment`, `supported_assessment`, `minimal_evidence_pack`).
Proves: the Causality lens REJECTs a bare correlation with no registered
transmission mechanism (SC#2 / Constitution 11); each lens reads its mapped
pre-compressed pack-facet slice (emptying that facet changes the verdict — not
narrative-only); the critique is transformation-pure (the input assessment is
byte-identical after critique); and an unresolvable config raises RuntimeError.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fingpt_core.contracts.evidence_pack import (
    ContradictionFacet,
    FacetIntegrity,
    HistoricalPercentileFacet,
    SignalFacet,
)

from core.agents.specialized_critic.base import SpecializedCritic
from core.agents.specialized_critic.lens_config import build_lens_config
from core.causal.mechanism_registry import CausalMechanismRegistry
from core.causal.seed import build_registry

# tests/agents/test_*.py -> tests/agents -> tests -> VM107
_VM107_ROOT = Path(__file__).resolve().parents[2]
_PROFILE_DIR = _VM107_ROOT / "registry" / "agent_profile"


@pytest.fixture(scope="module")
def registry() -> CausalMechanismRegistry:
    """The real reuse-first-seeded registry (absolute path — cwd-independent)."""
    return build_registry(_PROFILE_DIR)


def _critic(lens: str, registry: CausalMechanismRegistry) -> SpecializedCritic:
    return SpecializedCritic(build_lens_config(lens), registry=registry)


# ----------------------------------------------------------------- SC#2 (Causality)
def test_causality_rejects_bare_correlation(
    bare_correlation_assessment, minimal_evidence_pack, registry
):
    """SC#2 (Constitution 11): a directional 'signal' with NO registered mechanism -> REJECT."""
    verdict = _critic("CAUSALITY", registry).critique(
        bare_correlation_assessment, minimal_evidence_pack
    )
    assert verdict.verdict in ("REJECT", "REFINE")
    assert verdict.verdict == "REJECT"
    assert any(
        t.canonical_issue_id.value == "MECHANISM_UNREGISTERED"
        for t in verdict.refinement_targets
    )
    assert "MECHANISM_UNREGISTERED" in verdict.failure_modes
    # rationale cites the missing transmission mechanism
    assert "mechanism" in verdict.rationale.lower()
    # the target is claim-scoped and cites the assessment's claims field
    target = verdict.refinement_targets[0]
    assert target.scope == "CLAIM"
    assert target.target_field == "claims"
    assert target.source_critic_verdict_id == verdict.source_critic_verdict_id


def test_causality_accepts_supported(
    supported_assessment, minimal_evidence_pack, registry
):
    """A claim matching a seeded transmission mechanism (+ no strong contradiction) -> ACCEPT."""
    verdict = _critic("CAUSALITY", registry).critique(
        supported_assessment, minimal_evidence_pack
    )
    assert verdict.verdict == "ACCEPT"
    assert verdict.refinement_targets == []
    assert verdict.failure_modes == []


# ----------------------------------------------------------------- Evidence
def test_evidence_accepts_supported(
    supported_assessment, minimal_evidence_pack, registry
):
    verdict = _critic("EVIDENCE", registry).critique(
        supported_assessment, minimal_evidence_pack
    )
    assert verdict.verdict == "ACCEPT"


def test_evidence_unsupported_claim(
    supported_assessment, minimal_evidence_pack, registry
):
    """No supporting contributors/signals + no data_quality -> EVIDENCE_UNSUPPORTED."""
    stripped = minimal_evidence_pack.model_copy(
        update={"top_contributors": (), "top_signals": (), "data_quality": None}
    )
    verdict = _critic("EVIDENCE", registry).critique(supported_assessment, stripped)
    assert verdict.verdict in ("REFINE", "REJECT")
    assert any(
        t.canonical_issue_id.value == "EVIDENCE_UNSUPPORTED"
        for t in verdict.refinement_targets
    )


# ----------------------------------------------------------------- Market
def test_market_priced_in(supported_assessment, minimal_evidence_pack, registry):
    """A read at an extreme historical percentile -> ALREADY_PRICED_IN."""
    priced = minimal_evidence_pack.model_copy(
        update={
            "historical_percentile": HistoricalPercentileFacet(
                percentile=95.0, window="5y", integrity=FacetIntegrity.NEUTRAL
            )
        }
    )
    verdict = _critic("MARKET", registry).critique(supported_assessment, priced)
    assert verdict.verdict == "REFINE"
    assert any(
        t.canonical_issue_id.value == "ALREADY_PRICED_IN"
        for t in verdict.refinement_targets
    )


# ----------------------------------------------------------------- Risk
def test_risk_no_invalidation_condition(
    supported_assessment, minimal_evidence_pack, registry
):
    """An assessment with empty invalidation_conditions -> NO_INVALIDATION_CONDITION."""
    no_inval = supported_assessment.model_copy(update={"invalidation_conditions": ()})
    verdict = _critic("RISK", registry).critique(no_inval, minimal_evidence_pack)
    assert verdict.verdict in ("REFINE", "REJECT")
    assert any(
        t.canonical_issue_id.value == "NO_INVALIDATION_CONDITION"
        for t in verdict.refinement_targets
    )


# ----------------------------------------------------------------- Model
def test_model_degrading(supported_assessment, minimal_evidence_pack, registry):
    """A STALE domain_state integrity -> MODEL_DEGRADING."""
    stale_state = minimal_evidence_pack.domain_state.model_copy(
        update={"integrity": FacetIntegrity.STALE}
    )
    degraded = minimal_evidence_pack.model_copy(update={"domain_state": stale_state})
    verdict = _critic("MODEL", registry).critique(supported_assessment, degraded)
    assert verdict.verdict in ("REFINE", "REJECT")
    assert any(
        t.canonical_issue_id.value == "MODEL_DEGRADING"
        for t in verdict.refinement_targets
    )


# ----------------------------------------------------------------- facet-slice reads (not narrative-only)
def _facet_toggle_cases(minimal_evidence_pack, supported_assessment):
    """(lens, assessment, pack_with_facet, pack_without_facet) — verdict must differ."""
    stale_state = minimal_evidence_pack.domain_state.model_copy(
        update={"integrity": FacetIntegrity.STALE}
    )
    neutral_state = minimal_evidence_pack.domain_state  # already NEUTRAL
    return [
        (
            "EVIDENCE",
            supported_assessment,
            minimal_evidence_pack,  # has contributors/signals -> ACCEPT
            minimal_evidence_pack.model_copy(
                update={"top_contributors": (), "top_signals": (), "data_quality": None}
            ),
        ),
        (
            "CAUSALITY",
            supported_assessment,
            minimal_evidence_pack.model_copy(
                update={
                    "contradictions": (
                        ContradictionFacet(
                            claim_a="registered mechanism holds",
                            claim_b="pack evidence contradicts it",
                            severity=0.9,
                        ),
                    )
                }
            ),  # strong contradiction -> REFINE
            minimal_evidence_pack.model_copy(update={"contradictions": ()}),  # -> ACCEPT
        ),
        (
            "MARKET",
            supported_assessment,
            minimal_evidence_pack.model_copy(
                update={
                    "historical_percentile": HistoricalPercentileFacet(
                        percentile=95.0, window="5y", integrity=FacetIntegrity.NEUTRAL
                    )
                }
            ),  # priced-in -> REFINE
            minimal_evidence_pack.model_copy(update={"historical_percentile": None}),
        ),
        (
            "RISK",
            supported_assessment,
            minimal_evidence_pack.model_copy(
                update={
                    "excluded_signals": (
                        SignalFacet(
                            signal_id="oil_futures_curve",
                            importance=0.8,
                            excluded_reason="material signal dropped",
                        ),
                    )
                }
            ),  # material exclusion -> REFINE
            minimal_evidence_pack.model_copy(update={"excluded_signals": ()}),
        ),
        (
            "MODEL",
            supported_assessment,
            minimal_evidence_pack.model_copy(update={"domain_state": stale_state}),
            minimal_evidence_pack.model_copy(update={"domain_state": neutral_state}),
        ),
    ]


@pytest.mark.parametrize("lens", ["EVIDENCE", "CAUSALITY", "MARKET", "RISK", "MODEL"])
def test_lens_reads_its_facet_slice(
    lens, supported_assessment, minimal_evidence_pack, registry
):
    """Emptying a lens's mapped pack facet changes its verdict (proves not narrative-only)."""
    cases = {
        c[0]: c
        for c in _facet_toggle_cases(minimal_evidence_pack, supported_assessment)
    }
    _lens, assessment, pack_with, pack_without = cases[lens]
    critic = _critic(lens, registry)
    v_with = critic.critique(assessment, pack_with).verdict
    v_without = critic.critique(assessment, pack_without).verdict
    assert v_with != v_without, (
        f"{lens} verdict did not change when its facet was emptied "
        f"({v_with} -> {v_without}) — it is reading narrative only, not the facet"
    )
    # the facet toggles the verdict between ACCEPT and a non-ACCEPT finding
    assert "ACCEPT" in {v_with, v_without}


# ----------------------------------------------------------------- purity
@pytest.mark.parametrize("lens", ["EVIDENCE", "CAUSALITY", "MARKET", "RISK", "MODEL"])
def test_critique_is_transformation_pure(
    lens, bare_correlation_assessment, minimal_evidence_pack, registry
):
    """The input assessment is byte-identical after critique — a critic never rewrites it."""
    before = bare_correlation_assessment.model_dump()
    verdict = _critic(lens, registry).critique(
        bare_correlation_assessment, minimal_evidence_pack
    )
    after = bare_correlation_assessment.model_dump()
    assert after == before, f"{lens} mutated the input assessment (purity breach)"
    # critics hold only the reject/veto ceiling: no ACCEPT-with-rewrite, no skills loaded
    assert verdict.verdict in ("ACCEPT", "REFINE", "REJECT")
    assert verdict.loaded_skills == []
    if verdict.verdict == "ACCEPT":
        assert verdict.refinement_targets == []


# ----------------------------------------------------------------- reproducibility + provenance
def test_verdict_is_reproducible_and_fully_populated(
    bare_correlation_assessment, minimal_evidence_pack, registry
):
    critic = _critic("CAUSALITY", registry)
    v1 = critic.critique(bare_correlation_assessment, minimal_evidence_pack)
    v2 = _critic("CAUSALITY", registry).critique(
        bare_correlation_assessment, minimal_evidence_pack
    )
    assert v1.registry_snapshot_hash and len(v1.registry_snapshot_hash) == 64
    assert v1.registry_snapshot_hash == v2.registry_snapshot_hash
    assert v1.source_critic_verdict_id == v2.source_critic_verdict_id
    assert v1.confidence == v2.confidence


# ----------------------------------------------------------------- no-config RuntimeError (no stub)
def test_unresolvable_config_raises_runtimeerror(
    supported_assessment, minimal_evidence_pack
):
    critic = SpecializedCritic()  # no lens_config, no profile_source
    with pytest.raises(RuntimeError):
        critic.critique(supported_assessment, minimal_evidence_pack)
