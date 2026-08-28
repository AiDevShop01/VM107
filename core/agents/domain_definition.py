"""Phase 169 Plan 02 (D-07 / D-11) — typed DomainDefinition + safe_load loader.

The `DomainDefinition` is the per-domain *knowledge* config the generic
`DomainAgent` base (domain_agent.py) consumes to produce deterministic,
LLM-free assessment content. It is the structured `domain_definition:` block
that lives in `registry/agent_profile/vm107.<slug>_domain_analyst.yaml`
(D-11 — NOT a parallel `macro/config/` tree; the profile stays the single
authoritative index). This module defines the schema; Plan 169-04 authors the
12 real blocks against it.

Design locks honored here:
- **safe_load ONLY (ASVS V5).** `from_profile` parses YAML exclusively via
  `yaml.safe_load` — never `yaml.load` — because the block is untrusted-shaped
  config parsed at boot/runtime (threat T-169-02-04).
- **Determinism-first (Constitution 16, D-07).** `reasoning_rules` carries the
  `current_state` classifier thresholds, the claim templates, and the
  invalidation thresholds. The classifier is a pure threshold walk — the label
  is *assigned*, never authored by an LLM. This module holds NO engine import
  and NO LLM SDK import (guarded by test_domain_base_engine_lock.py, Task 3).
- **Large prose by reference (D-11).** Ontology / knowledge.md are path strings,
  never inlined — the structured, validated fields stay small and typed.
- **Frozen + closed models.** Every model is frozen `extra="forbid"`; ordered
  collections are tuples for frozen-safety (mirrors the fingpt_core contracts).
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class SignalRoles(BaseModel):
    """Lead / lag signal roles for the domain (D-11 signal roles)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lead: tuple[str, ...] = ()
    lag: tuple[str, ...] = ()


class StateRule(BaseModel):
    """One deterministic `current_state` classifier rule (D-07).

    A rule fires when EVERY bound it declares is satisfied by the copied
    level/momentum/surprise. Bounds that are `None` are simply not tested; a
    bound over a value that is itself `None` never matches (an unmeasured value
    cannot satisfy a threshold — `Unknown != Neutral`).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: str = Field(min_length=1, description="The current_state label this rule assigns.")
    level_min: float | None = None
    level_max: float | None = None
    momentum_min: float | None = None
    momentum_max: float | None = None
    surprise_min: float | None = None
    surprise_max: float | None = None

    def matches(
        self,
        level: float | None,
        momentum: float | None,
        surprise: float | None,
    ) -> bool:
        checks: tuple[tuple[float | None, float | None, str], ...] = (
            (self.level_min, level, "ge"),
            (self.level_max, level, "le"),
            (self.momentum_min, momentum, "ge"),
            (self.momentum_max, momentum, "le"),
            (self.surprise_min, surprise, "ge"),
            (self.surprise_max, surprise, "le"),
        )
        for bound, value, op in checks:
            if bound is None:
                continue
            if value is None:
                return False  # cannot satisfy a threshold on an unmeasured value
            if op == "ge" and not (value >= bound):
                return False
            if op == "le" and not (value <= bound):
                return False
        return True


class ClaimTemplate(BaseModel):
    """A falsifiable claim template (D-07) — real, non-empty, NOT a stub.

    subject/predicate/object are `str.format`-style templates filled at assess
    time from the copied state (`{state}`, `{level}`, `{momentum}`, `{domain}`,
    `{geography}`). The class + horizon fix how the claim is falsified.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_class: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object: str = Field(min_length=1)
    horizon: str = Field(min_length=1)
    invalidation_conditions: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()


class ReasoningRules(BaseModel):
    """The deterministic reasoning tables (D-07).

    `state_rules` + `default_state` are the `current_state` classifier;
    `claim_templates` generate the falsifiable `claims[]`; assessment-level
    `invalidation_conditions` are the whole-assessment falsifiers.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    default_state: str = Field(min_length=1)
    state_rules: tuple[StateRule, ...] = ()
    claim_templates: tuple[ClaimTemplate, ...] = ()
    invalidation_conditions: tuple[str, ...] = ()

    def classify(
        self,
        level: float | None,
        momentum: float | None,
        surprise: float | None,
    ) -> str:
        """Return the deterministic `current_state` label (first matching rule wins).

        Pure — no IO, no LLM, no wall-clock. The label is assigned by the first
        `StateRule` whose bounds are all satisfied; otherwise `default_state`.
        """
        for rule in self.state_rules:
            if rule.matches(level, momentum, surprise):
                return rule.state
        return self.default_state


# ---------------------------------------------------------------------------
# DomainDefinition — the typed per-domain knowledge config
# ---------------------------------------------------------------------------


class DomainDefinition(BaseModel):
    """The typed, validated `domain_definition:` block (D-11).

    Structured fields are inline + validated; large prose (ontology,
    knowledge.md) is referenced by path. `version` is surfaced as
    `domain_definition_version` for the AssessmentCache cache_key (D-09).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(min_length=1, description="Config version, surfaced as domain_definition_version.")
    knowledge_version: str = Field(min_length=1)
    indicators: tuple[str, ...] = ()
    signal_roles: SignalRoles = SignalRoles()
    horizons: tuple[str, ...] = ()
    calendar: str | None = None
    materiality_thresholds: dict[str, float] = Field(default_factory=dict)
    evaluation: dict[str, str] = Field(default_factory=dict)
    reasoning_rules: ReasoningRules
    ontology_path: str | None = None
    knowledge_path: str | None = None

    @property
    def domain_definition_version(self) -> str:
        """The cache-key alias for `version` (D-09)."""
        return self.version

    @classmethod
    def from_profile(cls, source: "str | Path | dict") -> "DomainDefinition":
        """Parse a `domain_definition:` block from a profile path or mapping.

        A path is read + parsed with `yaml.safe_load` ONLY (never `yaml.load`,
        ASVS V5 / T-169-02-04). When the parsed mapping carries a top-level
        `domain_definition:` key it is extracted; a bare block mapping is used
        as-is. A block missing a required key raises a clear `ValidationError`;
        an absent block raises `KeyError`.
        """
        if isinstance(source, (str, Path)):
            text = Path(source).read_text()
            data = yaml.safe_load(text)  # safe_load ONLY — ASVS V5
            if not isinstance(data, dict):
                raise ValueError(f"profile {source!r} did not parse to a mapping")
            if "domain_definition" not in data:
                raise KeyError(f"profile {source!r} has no top-level 'domain_definition:' block")
            block = data["domain_definition"]
        elif isinstance(source, dict):
            block = source.get("domain_definition", source)
        else:
            raise TypeError(f"from_profile expects a path or mapping, got {type(source).__name__}")

        if not isinstance(block, dict):
            raise ValueError("'domain_definition' block is not a mapping")
        return cls(**block)


__all__ = [
    "DomainDefinition",
    "ReasoningRules",
    "StateRule",
    "ClaimTemplate",
    "SignalRoles",
]
