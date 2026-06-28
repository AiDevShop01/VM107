"""Phase 95 Wave 0 stub — domain analyst contract tests (Plan 95-12).

Parameterized over the canonical 12 macro domains (CONTEXT §A). Each
domain has a paired Specialist Analyst (VM107 agent); the contract test
ensures each Analyst:

1. Returns a SpecialistResponse (Phase 94 contract) with the correct
   envelope shape.
2. Never recomputes the domain score (LLM-FREE compute lock — the score
   is computed in VM102.DomainEngine and passed through; the analyst
   only enriches with narrative + citations).

Both invariants are parameterized over all 12 domains so a regression in
any single analyst surfaces immediately.

Tests xfailed until Plan 95-12 lands the 12 analyst agents.
"""

from __future__ import annotations

import pytest


# Per CONTEXT §A canonical 12 — used by every parameterized test in Phase 95.
DOMAIN_SLUGS = [
    "growth",
    "inflation",
    "labour",
    "housing",
    "credit",
    "monetary_policy",
    "fiscal",
    "external_sector",
    "manufacturing",
    "consumer",
    "financial_conditions",
    "commodities",
]


@pytest.mark.parametrize("slug", DOMAIN_SLUGS)
@pytest.mark.xfail(
    strict=False,
    reason="Wave 0 stub — implemented in Plan 95-12 (Domain Analysts)",
)
def test_returns_specialist_response_shape(slug):
    """Each of the 12 domain analysts returns a SpecialistResponse with
    the full Phase 94 envelope (status, agent, confidence, citations,
    limitations, depends_on, provenance, execution_time_ms).
    """
    raise NotImplementedError(f"Wave 0 stub — Plan 95-12 ({slug})")


@pytest.mark.parametrize("slug", DOMAIN_SLUGS)
@pytest.mark.xfail(
    strict=False,
    reason="Wave 0 stub — implemented in Plan 95-12 (Domain Analysts)",
)
def test_never_recomputes_score(slug):
    """Static-grep guard: each analyst MUST consume the domain score
    computed by VM102.DomainEngine; it MUST NOT re-derive a score from
    raw basket indicators (LLM-FREE compute lock).
    """
    raise NotImplementedError(f"Wave 0 stub — Plan 95-12 ({slug})")
