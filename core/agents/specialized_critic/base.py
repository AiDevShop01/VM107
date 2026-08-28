"""Phase 170 Task 1 (D-01 / D-02 / D-05) — the `SpecializedCritic(lens)` base.

The shared critique workflow all five lenses run — the direct mirror of 169's
`DomainAgent(domain)` base: ONE base + a frozen `LensConfig` injected per lens,
concrete behavior is config, not subclasses.

Path choice (mirror `core/agents/domain_agent.py`): this file lives OUTSIDE any
per-slug static-grep path; its own engine-lock is closed by the sibling test
`tests/agents/test_specialized_critic_engine_lock.py` (Task 3). The base is
LLM-free (no LLM-SDK import — Pitfall 5); the critique path's effective
`max_cost_usd` stays 0.0.

`critique(assessment, pack) -> CriticVerdict`:
- COPIES facts from the typed inputs (never recomputes engine state — engine-lock).
- Reads ONLY the lens's mapped pre-compressed pack-facet slice (SPEC §2 — never
  narrative-only); the slice is enforced by `LensConfig.facets`.
- Delegates the ACCEPT/REFINE/REJECT decision + `RefinementTarget[]` to the lens
  rule bundle (lenses.py) — a pure first-matching-rule-wins classifier.
- Builds a fully-populated, reproducible `CriticVerdict`: `loaded_skills=[]`
  (deterministic), `failure_modes` = the canonical IDs actually raised, and a
  real `registry_snapshot_hash` (hash of lens config version + registry_version +
  pack state_version). Transformation-pure: it NEVER mutates the assessment and
  NEVER returns ACCEPT-with-rewrite (05, D-05 — critics hold only the reject/veto
  ceiling). memory_scope semantics are all-NONE — a critic judges an artifact.
"""
from __future__ import annotations

import hashlib

# READ-ONLY input contracts (produced by 168/169; NEVER redefine locally — Pitfall 4)
from fingpt_core.contracts.assessment import DomainAssessment
from fingpt_core.contracts.evidence_pack import DomainEvidencePack

# VM107-local OUTPUT contract (D-06)
from core.contracts.schemas import CriticVerdict

# Net-new SC#2 registry (Plan 02) — the Causality lens's mechanism source.
from core.causal.mechanism_registry import CausalMechanismRegistry

from core.agents.specialized_critic.lens_config import LensConfig


class SpecializedCritic:
    """Config-driven critic base (D-01): one base, five injected `LensConfig`s.

    Construct with an injected `LensConfig` (the test + panel path) or a
    `profile_source` a `critic_definition:` block loads from; with neither,
    `critique()` raises a clear `RuntimeError` — never a silent stub verdict.
    The `CausalMechanismRegistry` is injectable too (tests inject a pre-seeded
    one); otherwise it is built lazily reuse-first from the 169 profile blocks.
    """

    def __init__(
        self,
        lens_config: LensConfig | None = None,
        *,
        registry: CausalMechanismRegistry | None = None,
        profile_source: "str | dict | None" = None,
    ) -> None:
        # Inject for tests/panel; resolve lazily otherwise.
        self._lens_config = lens_config
        self._registry = registry
        self._profile_source = profile_source

    # ------------------------------------------------------- resolution
    def _resolve_config(self) -> LensConfig:
        """Return the LensConfig, loading from the profile if not injected.

        Raises a clear, actionable `RuntimeError` when no config is resolvable —
        never returns a stub (D-01a discipline mirrors DomainAgent._resolve_definition).
        """
        if self._lens_config is not None:
            return self._lens_config
        if self._profile_source is not None:
            try:
                self._lens_config = LensConfig.from_profile(self._profile_source)
            except Exception as exc:  # clear, actionable error — no silent stub
                raise RuntimeError(
                    f"{type(self).__name__}.critique requires a LensConfig: no loadable "
                    f"'critic_definition:' block ({exc}). Pass lens_config=... "
                    f"(e.g. build_lens_config('EVIDENCE')) or a valid profile_source."
                ) from exc
            return self._lens_config
        raise RuntimeError(
            f"{type(self).__name__}.critique requires a LensConfig: none was injected and "
            f"no profile_source was given. Pass lens_config=... (e.g. "
            f"build_lens_config('CAUSALITY')) or profile_source=... — no silent stub."
        )

    def _resolve_registry(self) -> CausalMechanismRegistry:
        """Return the CausalMechanismRegistry, building it lazily reuse-first if absent."""
        if self._registry is None:
            from core.causal.seed import build_registry

            self._registry = build_registry()
        return self._registry

    # ------------------------------------------------------- critique
    def critique(
        self, assessment: DomainAssessment, pack: DomainEvidencePack
    ) -> CriticVerdict:
        """Emit one deterministic, falsifiable `CriticVerdict` for this lens.

        Pure — no IO beyond the lazy registry seed, no LLM, no wall-clock. The
        input `assessment` is never mutated (purity, D-05).
        """
        config = self._resolve_config()
        registry = self._resolve_registry()

        # Read ONLY this lens's mapped pack-facet slice (SPEC §2 — never narrative-only).
        facet_slice = self._read_facet_slice(pack, config)

        # Reproducible provenance BEFORE the decision (so RefinementTargets can cite it).
        snapshot_hash = self._registry_snapshot_hash(config, registry, pack)
        verdict_id = self._verdict_id(config, assessment, snapshot_hash)

        # Delegate the ACCEPT/REFINE/REJECT decision to the lens rule bundle.
        from core.agents.specialized_critic.lenses import evaluate_lens

        verdict_label, confidence, rationale, targets = evaluate_lens(
            config=config,
            assessment=assessment,
            facet_slice=facet_slice,
            registry=registry,
            verdict_id=verdict_id,
        )

        # failure_modes = the canonical IDs actually raised (non-empty on REFINE/REJECT).
        failure_modes = sorted({t.canonical_issue_id.value for t in targets})

        return CriticVerdict(
            verdict=verdict_label,
            confidence=confidence,
            refinement_targets=targets,
            failure_modes=failure_modes,
            rationale=rationale,
            loaded_skills=[],  # deterministic — no skills loaded (D-02)
            source_critic_verdict_id=verdict_id,
            registry_snapshot_hash=snapshot_hash,
        )

    # ------------------------------------------------------- internals
    @staticmethod
    def _read_facet_slice(pack: DomainEvidencePack, config: LensConfig) -> dict:
        """COPY only the lens's mapped facets off the pack (never the whole pack)."""
        return {name: getattr(pack, name) for name in config.facets}

    @staticmethod
    def _registry_snapshot_hash(
        config: LensConfig, registry: CausalMechanismRegistry, pack: DomainEvidencePack
    ) -> str:
        """Reproducible provenance hash: lens config version + registry_version + pack state_version."""
        blob = (
            f"{config.lens}|{config.version}|{registry.registry_version}|"
            f"{pack.identity.state_version}"
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @staticmethod
    def _verdict_id(
        config: LensConfig, assessment: DomainAssessment, snapshot_hash: str
    ) -> str:
        """A deterministic per-verdict id (no wall-clock — reproducible for a given input)."""
        first_claim = assessment.claims[0].claim_id if assessment.claims else ""
        blob = f"{config.lens}|{assessment.state_version}|{first_claim}|{snapshot_hash}"
        digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
        return f"scv-{config.lens.lower()}-{digest}"


__all__ = ["SpecializedCritic"]
