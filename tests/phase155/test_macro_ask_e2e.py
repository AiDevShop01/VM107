"""Phase 155 AC#4 — inflation+growth end-to-end (router → executor → ≥2 specialists → synth).

Drives a cross-pillar query through the real ``MacroAskRouter`` (with the stub registry) into
``MacroAskExecutor``, fanning out to ≥2 specialists and composing via the chief-economist
``synthesize``. Asserts the composed ``answer`` is non-empty and cites BOTH inflation and growth
with per-specialist provenance (deterministic-template output is acceptable).

Target (built in 155-03): ``agents.macro_ask_executor.executor.MacroAskExecutor``. RED by import
until then.
"""
from __future__ import annotations

# RED-on-target: not built until 155-03.
from agents.macro_ask_executor.executor import MacroAskExecutor
from agents.macro_ask_router.agent import MacroAskRouter


def test_inflation_growth_e2e_cites_both(stub_registry, stub_pillar_fetcher):
    """AC#4: an inflation+growth question composes an answer citing both pillars end-to-end."""
    router = MacroAskRouter(stub_registry)
    plan = router.invoke("Why is inflation cooling while growth holds up?", {})
    assert len(plan["required_agents"]) >= 2

    executor = MacroAskExecutor(registry=stub_registry, pillar_fetcher=stub_pillar_fetcher())
    composed = executor.run(query="Why is inflation cooling while growth holds up?", plan=plan)

    answer = composed["answer"]
    assert answer  # non-empty composed answer
    lowered = answer.lower()
    assert "inflation" in lowered
    assert "growth" in lowered
    # Per-specialist provenance survives synthesis (paragraph attribution map is populated).
    assert composed["_paragraph_attribution"]
