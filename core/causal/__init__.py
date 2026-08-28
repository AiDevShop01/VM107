"""Phase 170 Plan 02 (D-03) — the net-new `CausalMechanismRegistry` package.

A small, deterministic, LLM-free per-`(domain, claim_class, subject/predicate)`
transmission-mechanism store the Causality Critic checks a claim against
(Constitution rule 11 — correlation != causation). A claim whose key has NO
registered mechanism is the deterministic REJECT signal (SC#2).

Design locks (mirrored from `core/agents/domain_definition.py`, the 169 analog):
- **Frozen closed contracts.** Every model is `ConfigDict(frozen=True, extra="forbid")`.
- **safe_load ONLY (ASVS V5 / T-170-02-01).** The seed parses profile YAML via
  `yaml.safe_load` exclusively — never `yaml.load`.
- **Determinism-first (Constitution 16, T-170-02-03).** The store holds no
  wall-clock, no IO, no LLM SDK import; `registry_version` is a content hash so
  downstream verdicts derive a reproducible `registry_snapshot_hash`.
- **NOT backed by `core/contradiction/` (D-03).** Divergence-grading is a
  different semantic from mechanism plausibility.
"""
from __future__ import annotations

from core.causal.mechanism_registry import CausalMechanismRegistry, MechanismRecord
from core.causal.seed import build_registry

__all__ = [
    "CausalMechanismRegistry",
    "MechanismRecord",
    "build_registry",
]
