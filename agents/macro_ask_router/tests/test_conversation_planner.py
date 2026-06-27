"""Phase 94-06 — ConversationPlanner heuristic + registry-discovery + LLM-fallback tests."""

from __future__ import annotations

from agents.macro_ask_router.conversation_planner import ConversationPlanner, Plan


class _StubRegistry:
    def __init__(self, agents: list[str] | None = None) -> None:
        if agents is None:
            agents = [
                "vm107.growth_analyst",
                "vm107.inflation_analyst",
                "vm107.liquidity_analyst",
                "vm107.risk_analyst",
                "vm107.central_bank_summariser",
                "vm107.macro_forecast_narrator",
                "vm107.theme_monitor",
            ]
        self._agents = list(agents)

    def add(self, agent_id: str) -> None:
        self._agents.append(agent_id)

    def list_capabilities(self, *, type=None, tags=None):
        return [{"id": a, "type": "agent_profile"} for a in self._agents]


def test_heuristic_routes_inflation_query():
    planner = ConversationPlanner(_StubRegistry())
    plan = planner.plan(query="Why is inflation cooling?", dashboard_context={})
    assert "vm107.inflation_analyst" in plan.required_agents


def test_heuristic_routes_inflation_query_cross_pillar_when_growth_selected():
    """When the user is on Growth pillar but asks about Inflation, both agents fire."""
    planner = ConversationPlanner(_StubRegistry())
    plan = planner.plan(
        query="Why is inflation cooling?",
        dashboard_context={"selected_pillar": "Growth"},
    )
    assert "vm107.inflation_analyst" in plan.required_agents
    assert "vm107.growth_analyst" in plan.required_agents


def test_heuristic_routes_compare_query_picks_country_intelligence_when_available():
    registry = _StubRegistry()
    registry.add("vm107.country_intelligence_agent")
    planner = ConversationPlanner(registry)
    plan = planner.plan(query="compare US vs EU inflation", dashboard_context={})
    assert "vm107.country_intelligence_agent" in plan.required_agents
    assert "vm107.inflation_analyst" in plan.required_agents


def test_heuristic_routes_compare_query_skips_country_intelligence_when_unregistered():
    """Forward-link agent is not yet registered → planner doesn't fabricate it."""
    planner = ConversationPlanner(_StubRegistry())  # no country_intelligence
    plan = planner.plan(query="compare US vs EU inflation", dashboard_context={})
    assert "vm107.country_intelligence_agent" not in plan.required_agents
    assert "vm107.inflation_analyst" in plan.required_agents


def test_llm_fallback_for_free_text():
    """Unmatched query falls back to the injected classifier."""
    classifier_calls: list[tuple[str, list[str]]] = []

    def fake_classifier(q, options):
        classifier_calls.append((q, options))
        return ["vm107.risk_analyst"]

    planner = ConversationPlanner(_StubRegistry(), llm_classifier=fake_classifier)
    plan = planner.plan(
        query="what should I do about my portfolio",
        dashboard_context={},
    )
    assert plan.required_agents == ["vm107.risk_analyst"]
    assert classifier_calls, "classifier should have been invoked on no-heuristic-match path"


def test_registry_driven_specialist_discovery():
    """Adding a new specialist via the registry → next plan invocation includes it.

    Heuristic-only catalogue exposure is NOT enough — the planner must use
    list_capabilities(), so registering a new specialist for an existing
    keyword family changes the plan WITHOUT any code change in the planner.
    """
    registry = _StubRegistry(agents=[])  # empty registry — nothing to route to
    planner = ConversationPlanner(registry)
    plan_before = planner.plan(query="inflation outlook", dashboard_context={})
    assert plan_before.required_agents == []

    # Add the specialist post-construction.
    registry.add("vm107.inflation_analyst")
    plan_after = planner.plan(query="inflation outlook", dashboard_context={})
    assert "vm107.inflation_analyst" in plan_after.required_agents


def test_plan_execution_order_parallel_when_multiple_specialists():
    planner = ConversationPlanner(_StubRegistry())
    plan = planner.plan(
        query="What is inflation and growth doing?",
        dashboard_context={},
    )
    assert len(plan.required_agents) >= 2
    assert plan.execution_order == "parallel"


def test_plan_execution_order_sequential_when_single_specialist():
    planner = ConversationPlanner(_StubRegistry())
    plan = planner.plan(query="What's the Fed up to?", dashboard_context={})
    assert plan.required_agents == ["vm107.central_bank_summariser"]
    assert plan.execution_order == "sequential"


def test_expected_latency_is_finite():
    planner = ConversationPlanner(_StubRegistry())
    plan = planner.plan(query="inflation outlook", dashboard_context={})
    assert isinstance(plan.expected_latency_seconds, float)
    assert 0 < plan.expected_latency_seconds < 60


def test_plan_dataclass_has_no_answer_field():
    """Plan.required_agents/execution_order/expected_latency_seconds — and that's it.

    Adding an 'answer' field would violate the §J pure-classifier lock.
    """
    fields = set(Plan.__dataclass_fields__.keys())
    assert "answer" not in fields, "Plan must NOT have an 'answer' field (§J)"
    assert {"required_agents", "execution_order", "expected_latency_seconds"} <= fields
