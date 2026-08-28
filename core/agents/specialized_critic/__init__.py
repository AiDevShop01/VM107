"""Phase 170 (D-01 / D-02) — the specialized critic panel package.

ONE config-driven `SpecializedCritic(lens)` base (base.py) + a frozen `LensConfig`
schema (lens_config.py) + five deterministic lens rule bundles (lenses.py), the
direct mirror of 169's `DomainAgent(domain)` one-base-N-configs build. Each lens
adversarially reviews a producer's typed `DomainAssessment` PLUS its pre-compressed
`DomainEvidencePack` facets and emits a real, falsifiable `CriticVerdict`
(ACCEPT / REFINE / REJECT) with typed `RefinementTarget[]`.

Determinism (D-02, NON-NEGOTIABLE): this package is LLM-free — no
openai/anthropic/litellm import anywhere — and the critique path's effective
`max_cost_usd` stays 0.0. Its engine-lock is closed by the sibling test
`tests/agents/test_specialized_critic_engine_lock.py`, whose glob covers BOTH
this package and `core/causal/` so a future file cannot silently smuggle an LLM
or engine-recompute import back in (Pitfall 3). Lenses are transformation-pure:
they hold only the reject/veto ceiling (05, D-05), never approve-with-rewrite,
and never mutate the assessment they judge.
"""
from __future__ import annotations

from core.agents.specialized_critic.base import SpecializedCritic
from core.agents.specialized_critic.lens_config import (
    LensConfig,
    build_lens_config,
    default_lens_configs,
)

__all__ = [
    "SpecializedCritic",
    "LensConfig",
    "build_lens_config",
    "default_lens_configs",
]
