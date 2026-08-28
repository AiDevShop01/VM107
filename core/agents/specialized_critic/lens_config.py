"""Phase 170 Task 1 (D-01 / D-01a) — frozen `LensConfig` schema + safe_load loader.

The `LensConfig` is the per-lens *knowledge* config the generic
`SpecializedCritic` base (base.py) consumes to run a deterministic, LLM-free
critique. It is the direct analog of 169's `DomainDefinition`: a frozen
`extra="forbid"` Pydantic block parsed with `yaml.safe_load` ONLY (ASVS V5), the
single authoritative index for a lens's failure mode, which pack facets it reads,
its refinement target coordinates, and its rule thresholds.

Five lenses share this ONE schema (Evidence / Causality / Market / Risk / Model);
each concrete lens is a config, not a subclass (D-01). `default_lens_configs()`
returns the five validated defaults the panel + tests use — real typed configs,
never a stub. Large prose stays out; only small typed thresholds live here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

# The five lens identifiers (Literal-validated on the config).
LensName = Literal["EVIDENCE", "CAUSALITY", "MARKET", "RISK", "MODEL"]

# The refinement scope each lens targets (a subset of RefinementTarget.scope; the
# strategy scopes STRATEGY_SPEC/CODE_MODULE never apply to a domain-assessment critique).
LensScope = Literal["DOMAIN_ASSESSMENT", "CLAIM"]


class LensConfig(BaseModel):
    """One validated critic-lens config (frozen, closed contract — mirror 169).

    Carries the lens identity, the pre-compressed pack facets it is allowed to
    read (SPEC §2 — never narrative-only), the canonical failure-mode IDs it may
    emit, its `RefinementTarget` scope/target_field coordinates, and its rule
    thresholds. `extra="forbid"` + `frozen=True` mirror every VM107 contract.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(min_length=1, description="Config version — part of the registry_snapshot_hash.")
    lens: LensName
    facets: tuple[str, ...] = Field(
        min_length=1, description="DomainEvidencePack facet field names this lens is allowed to read."
    )
    failure_modes: tuple[str, ...] = Field(
        min_length=1, description="Canonical issue IDs this lens may emit (CanonicalIssueId members)."
    )
    scope: LensScope = "DOMAIN_ASSESSMENT"
    target_field: str = Field(min_length=1, description="The DomainAssessment/Claim field a finding targets.")

    # --- rule thresholds (union across the five lenses; each lens reads the ones it needs) ---
    # Evidence
    min_data_quality: float = Field(default=0.5, ge=0.0, le=1.0)
    min_supporting_evidence: int = Field(default=1, ge=0)
    # Causality
    contradiction_severity_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    # Market
    priced_in_percentile: float = Field(default=90.0, ge=0.0, le=100.0)
    # Risk
    material_excluded_importance: float = Field(default=0.5, ge=0.0, le=1.0)
    # Model
    min_model_coverage: float = Field(default=0.5, ge=0.0, le=1.0)

    @classmethod
    def from_profile(cls, source: "str | Path | dict") -> "LensConfig":
        """Parse a `critic_definition:` lens block from a profile path or mapping.

        A path is read + parsed with `yaml.safe_load` ONLY (never `yaml.load`,
        ASVS V5). When the parsed mapping carries a top-level `critic_definition:`
        key it is extracted; a bare block mapping is used as-is. A block missing a
        required key raises a clear `ValidationError`; an absent block raises
        `KeyError`. No silent stub — an unresolvable config is an error.
        """
        if isinstance(source, (str, Path)):
            text = Path(source).read_text()
            data = yaml.safe_load(text)  # safe_load ONLY — ASVS V5
            if not isinstance(data, dict):
                raise ValueError(f"profile {source!r} did not parse to a mapping")
            if "critic_definition" not in data:
                raise KeyError(f"profile {source!r} has no top-level 'critic_definition:' block")
            block = data["critic_definition"]
        elif isinstance(source, dict):
            block = source.get("critic_definition", source)
        else:
            raise TypeError(f"from_profile expects a path or mapping, got {type(source).__name__}")

        if not isinstance(block, dict):
            raise ValueError("'critic_definition' block is not a mapping")
        return cls(**block)


# ---------------------------------------------------------------------------
# The five validated default lens configs (real typed configs — NOT stubs).
#
# Lens -> facet slice map (finalized; SPEC §2 — each reads a DIFFERENT slice):
#   Evidence  -> top_contributors, top_signals, data_quality
#   Causality -> contradictions (+ CausalMechanismRegistry lookup, base-supplied)
#   Market    -> state_diff, historical_percentile
#   Risk      -> excluded_signals (+ assessment.invalidation_conditions)
#   Model     -> pack_integrity, domain_state, data_quality
# ---------------------------------------------------------------------------

_DEFAULT_VERSION = "1.0.0"

_DEFAULTS: dict[str, dict] = {
    "EVIDENCE": {
        "facets": ("top_contributors", "top_signals", "data_quality"),
        "failure_modes": ("EVIDENCE_UNSUPPORTED",),
        "scope": "CLAIM",
        "target_field": "claims",
    },
    "CAUSALITY": {
        "facets": ("contradictions",),
        "failure_modes": ("MECHANISM_UNREGISTERED",),
        "scope": "CLAIM",
        "target_field": "claims",
    },
    "MARKET": {
        "facets": ("state_diff", "historical_percentile"),
        "failure_modes": ("ALREADY_PRICED_IN",),
        "scope": "DOMAIN_ASSESSMENT",
        "target_field": "momentum",
    },
    "RISK": {
        "facets": ("excluded_signals",),
        "failure_modes": ("NO_INVALIDATION_CONDITION",),
        "scope": "DOMAIN_ASSESSMENT",
        "target_field": "invalidation_conditions",
    },
    "MODEL": {
        "facets": ("pack_integrity", "domain_state", "data_quality"),
        "failure_modes": ("MODEL_DEGRADING",),
        "scope": "DOMAIN_ASSESSMENT",
        "target_field": "integrity_state",
    },
}


def build_lens_config(lens: str) -> LensConfig:
    """Return the validated default `LensConfig` for one lens name.

    Real typed config (not a stub). Raises `KeyError` for an unknown lens so a
    typo can never silently resolve to a wrong lens.
    """
    key = lens.upper()
    if key not in _DEFAULTS:
        raise KeyError(f"unknown lens {lens!r}; known lenses: {sorted(_DEFAULTS)}")
    return LensConfig(version=_DEFAULT_VERSION, lens=key, **_DEFAULTS[key])  # type: ignore[arg-type]


def default_lens_configs() -> dict[str, LensConfig]:
    """The five validated default lens configs, keyed by lens name."""
    return {name: build_lens_config(name) for name in _DEFAULTS}


__all__ = [
    "LensConfig",
    "LensName",
    "LensScope",
    "build_lens_config",
    "default_lens_configs",
]
