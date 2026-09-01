"""Phase 155 AZE-01 + D-03 — router→specialist fan-out + specialist_ids alignment + fail-loud.

Target (built in 155-03): ``agents.macro_ask_executor.executor.MacroAskExecutor`` — loops the
router Plan's ``required_agents`` (parallel or sequential), collects a ``SpecialistResponse`` per
agent, and hands ``synthesize`` a ``specialist_ids`` list PARALLEL to the responses (required_agents
order) so the chief-economist synthesizer never raises the length-mismatch ``ValueError``. A single
specialist failure degrades honestly (confidence=0.0 sentinel named under ``limitations``); an empty
plan fails loud and NEVER calls ``synthesize`` with ``[]`` (T-155-03).

RED by import until 155-03.
"""
from __future__ import annotations

import pytest

# RED-on-target: not built until 155-03.
from agents.macro_ask_executor.executor import MacroAskExecutor


@pytest.mark.parametrize("execution_order", ["parallel", "sequential"])
def test_dispatch_loops_all_required_agents(
    stub_registry, stub_pillar_fetcher, fake_plan, execution_order
):
    """Both parallel and sequential dispatch fan out to EVERY required agent and collect a
    SpecialistResponse per agent — none dropped."""
    executor = MacroAskExecutor(registry=stub_registry, pillar_fetcher=stub_pillar_fetcher())
    plan = fake_plan(
        required_agents=["vm107.inflation_analyst", "vm107.growth_analyst"],
        execution_order=execution_order,
    )
    responses = executor.dispatch_all(plan=plan)
    assert len(responses) == 2
    assert all(r.answer for r in responses)


def test_specialist_ids_parallel_to_responses_no_valueerror(
    stub_registry, stub_pillar_fetcher, fake_plan
):
    """The executor passes specialist_ids parallel to responses in required_agents order, so
    ``synthesize`` never raises its length-mismatch ValueError."""
    executor = MacroAskExecutor(registry=stub_registry, pillar_fetcher=stub_pillar_fetcher())
    plan = fake_plan(required_agents=["vm107.inflation_analyst", "vm107.growth_analyst"])
    composed = executor.run(query="inflation and growth", plan=plan)  # must NOT raise ValueError
    assert composed["answer"]


def test_single_specialist_failure_degrades_honestly(
    stub_registry, stub_pillar_fetcher, fake_plan
):
    """One injected specialist failure yields a confidence=0.0 sentinel NAMED in synthesize
    ``limitations`` (degrade that section only), the other specialist still answers."""
    fetcher = stub_pillar_fetcher(degraded="Liquidity")  # liquidity snapshot missing → failure
    executor = MacroAskExecutor(registry=stub_registry, pillar_fetcher=fetcher)
    plan = fake_plan(
        required_agents=["vm107.inflation_analyst", "vm107.liquidity_analyst"]
    )
    composed = executor.run(query="inflation vs liquidity", plan=plan)
    assert composed["answer"]  # not collapsed
    assert any("liquidity" in lim.lower() for lim in composed["limitations"])


def test_empty_required_agents_fails_loud_without_synthesize(
    stub_registry, stub_pillar_fetcher, fake_plan, monkeypatch
):
    """Empty required_agents → fail-loud failure result; ``synthesize`` is NEVER called with []
    (T-155-03: an empty plan must not spoof a real synthesized answer)."""
    executor = MacroAskExecutor(registry=stub_registry, pillar_fetcher=stub_pillar_fetcher())

    called: list = []
    # Guard the synthesizer: if the executor ever calls it, record the args so we can assert
    # it was NOT called with an empty specialist list.
    if hasattr(executor, "_synthesizer"):
        monkeypatch.setattr(
            executor._synthesizer,
            "synthesize",
            lambda *a, **k: called.append((a, k)) or {},
        )

    result = executor.run(query="anything", plan=fake_plan(required_agents=[]))
    assert result.get("failed") is True or result.get("stop_reason") == "error"
    assert called == []  # synthesize NOT called with an empty plan
