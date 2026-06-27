"""Phase 94-06 — MacroAskRouter (PURE CLASSIFIER per §J).

The router is a pure classifier. It NEVER answers. It NEVER imports any
LLM client. Its sole responsibility is to dispatch a user query to a
combination of registered specialist agents and return an execution
plan describing required_agents / execution_order / expected_latency.

A static-grep test guard in
``agents/macro_ask_router/tests/test_router_never_answers.py`` enforces
the no-LLM-import + no-answer-emission contract — adding ``import openai``
or returning an ``answer`` key will turn that test RED.

The natural-language response is composed downstream by
:class:`agents.chief_economist_synthesizer.ChiefEconomistSynthesizer`,
not here.
"""

from __future__ import annotations

from typing import Any

from agents.macro_ask_router.conversation_planner import (
    CapabilityRegistryProtocol,
    ConversationPlanner,
)


class MacroAskRouter:
    """Pure-classifier router (§J)."""

    AGENT_ID = "vm107.macro_ask_router"

    def __init__(
        self,
        capability_registry: CapabilityRegistryProtocol,
        llm_classifier: Any | None = None,
    ) -> None:
        self.planner = ConversationPlanner(capability_registry, llm_classifier)

    def invoke(self, query: str, context: dict | None = None) -> dict:
        """Return an execution plan; NEVER an answer.

        Keys returned: ``required_agents``, ``execution_order``,
        ``expected_latency`` (seconds), ``reasoning``.
        """
        plan = self.planner.plan(query=query, dashboard_context=context or {})
        return {
            "required_agents": list(plan.required_agents),
            "execution_order": plan.execution_order,
            "expected_latency": plan.expected_latency_seconds,
            "reasoning": plan.reasoning,
        }


__all__ = ["MacroAskRouter"]
