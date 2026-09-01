"""Phase 155 (155-03) — MacroAskExecutor: router → specialist fan-out → synthesize.

The missing middle of the macro-ask pipeline (closes blocker B2 / AZE-01, lands AZE-07):

  1. ``run(query, plan=None, ...)`` gets a Plan (router-produced or injected), then for each
     ``required_agents`` id resolves the specialist (registry-gated, fail-loud), fetches its
     ``Pillar`` snapshot, and dispatches it under the AZE-07 ``SubagentResult`` envelope.
  2. Fan-out honours ``execution_order`` — ``"parallel"`` → ``asyncio.gather`` (one raise
     never cancels the batch, FAST_FAIL rationale Phase 47.2.1), ``"sequential"`` → an
     ordered awaited loop. The SYNC specialist ``.invoke()`` is bridged with
     ``asyncio.to_thread`` (chat.py::process is async; run() itself stays sync for callers).
  3. ``responses`` and ``specialist_ids`` are built from the SAME zipped iteration so they
     are provably parallel in ``required_agents`` order — the chief-economist ``synthesize``
     never raises its length-mismatch ``ValueError`` (Pitfall 2). A non-``completed`` section
     contributes a ``confidence=0.0`` sentinel (named under ``limitations``), never a real
     answer (T-155-09).
  4. An EMPTY plan fails loud and NEVER calls ``synthesize`` with ``[]`` (D-03 / T-155-03).

Scope = the 4 pillar analysts (D-02). A non-pillar routed id honestly degrades (RESEARCH
Open Q1) — it never fabricates and never crashes the batch.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agents.chief_economist_synthesizer.agent import ChiefEconomistSynthesizer
from agents.macro_ask_router.agent import MacroAskRouter
from contracts.economic_intelligence.specialist_response import SpecialistResponse
from contracts.economic_intelligence.subagent_contract import (
    SubagentRequest,
    SubagentResult,
)

from agents.macro_ask_executor.registry_adapter import RegistryAdapter
from agents.macro_ask_executor.resolver import (
    UnknownSpecialist,
    _sentinel_response,
    dispatch_specialist,
    load_tool_filter,
    resolve_specialist,
)

# id → PillarName (note the risk_analyst → "RiskAppetite" asymmetry, A1 CONFIRMED). A dotted
# id absent from this map is a non-pillar routed id → pillar None → honest degrade (Open Q1).
_ID_TO_PILLAR: dict[str, str] = {
    "vm107.growth_analyst": "Growth",
    "vm107.inflation_analyst": "Inflation",
    "vm107.liquidity_analyst": "Liquidity",
    "vm107.risk_analyst": "RiskAppetite",
}


class MacroAskExecutor:
    """Orchestrates the router → fan-out → synthesize macro-ask pipeline."""

    def __init__(
        self,
        *,
        registry: Any | None = None,
        pillar_fetcher: Any | None = None,
        **_ignored: Any,
    ) -> None:
        # In tests both are injected. In production the adapter/fetcher self-construct.
        self._registry = registry if registry is not None else RegistryAdapter()
        if pillar_fetcher is not None:
            self._pillar_fetcher = pillar_fetcher
        else:
            from agents.macro_ask_executor.pillar_fetcher import PillarSnapshotFetcher

            self._pillar_fetcher = PillarSnapshotFetcher()
        # First production constructor of the router (only tests built it before).
        self._router = MacroAskRouter(self._registry)
        self._synthesizer = ChiefEconomistSynthesizer()

    # ───────────────────────────────────────────────────────── per-specialist dispatch

    def build_subagent_request(
        self, agent_id: str, *, plan: dict | None = None
    ) -> SubagentRequest:
        """Build the AZE-07 request whose ``tool_filter`` carries the profile scope (D-02)."""
        return SubagentRequest(
            prompt=f"Explain the {agent_id} pillar assessment for the user's macro question.",
            output_schema="SpecialistResponse",
            tool_filter=load_tool_filter(agent_id),
            persona=agent_id,
            max_depth=1,
        )

    def dispatch_one(
        self, agent_id: str, *, plan: dict | None = None, context: dict | None = None
    ) -> SubagentResult:
        """Resolve + fetch pillar + dispatch ONE specialist under the AZE-07 envelope."""
        try:
            instance: object | None = resolve_specialist(agent_id, self._registry)
        except UnknownSpecialist:
            instance = None  # fail-loud handled in dispatch_specialist (stop_reason="error")

        pillar_name = _ID_TO_PILLAR.get(agent_id)  # None → non-pillar id → honest degrade
        pillar = self._pillar_fetcher.get(pillar_name) if pillar_name else None
        return dispatch_specialist(
            agent_id, instance, pillar, self._registry, context=context
        )

    # ───────────────────────────────────────────────────────── async fan-out (bridged)

    async def _fan_out(
        self, plan: dict, context: dict | None
    ) -> list[tuple[str, SubagentResult]]:
        agent_ids = list(plan["required_agents"])
        order = plan.get("execution_order", "parallel")

        async def _one(agent_id: str) -> SubagentResult:
            # Bridge the SYNC specialist .invoke() onto a thread so the batch stays async.
            return await asyncio.to_thread(
                self.dispatch_one, agent_id, plan=plan, context=context
            )

        if order == "parallel":
            # return_exceptions=True — one raise never cancels the batch (FAST_FAIL budget).
            results = await asyncio.gather(
                *[_one(a) for a in agent_ids], return_exceptions=True
            )
        else:  # "sequential" — ordered awaited loop
            results = []
            for a in agent_ids:
                results.append(await _one(a))

        normalised: list[tuple[str, SubagentResult]] = []
        for agent_id, result in zip(agent_ids, results):
            if isinstance(result, BaseException):
                # A raise that escaped dispatch → degrade honestly, never drop the id.
                normalised.append(
                    (
                        agent_id,
                        SubagentResult(
                            output="<specialist unavailable>",
                            structured=_sentinel_response(agent_id),
                            stop_reason="error",
                            diagnostic={
                                "agent_id": agent_id,
                                "error": type(result).__name__,
                            },
                        ),
                    )
                )
            else:
                normalised.append((agent_id, result))
        return normalised

    def dispatch_all(
        self, *, plan: dict, context: dict | None = None
    ) -> list[SpecialistResponse]:
        """Fan out to EVERY required agent; return a SpecialistResponse per agent (order kept).

        A degraded/errored section becomes a ``confidence=0.0`` sentinel — none are dropped.
        """
        paired = asyncio.run(self._fan_out(plan, context))
        responses: list[SpecialistResponse] = []
        for agent_id, result in paired:
            if result.stop_reason == "completed" and isinstance(
                result.structured, SpecialistResponse
            ):
                responses.append(result.structured)
            else:
                responses.append(_sentinel_response(agent_id))
        return responses

    # ───────────────────────────────────────────────────────── top-level orchestration

    def run(
        self,
        query: str,
        *,
        plan: dict | None = None,
        context: dict | None = None,
        journal_id: str | None = None,
    ) -> dict:
        """Router → fan-out → synthesize. Empty plan fails loud (synthesize NOT called)."""
        if plan is None:
            plan = self._router.invoke(query, context)

        agent_ids = list(plan.get("required_agents") or [])
        if not agent_ids:
            # D-03 / T-155-03: an empty plan must NEVER be spoofed as a real answer.
            return {
                "failed": True,
                "stop_reason": "error",
                "status": "failure",
                "answer": "",
                "limitations": ["no specialist matched this question"],
            }

        paired = asyncio.run(self._fan_out(plan, context))

        # Build responses + specialist_ids from the SAME iteration → provably parallel.
        responses: list[SpecialistResponse] = []
        specialist_ids: list[str] = []
        any_degraded = False
        any_usable = False
        for agent_id, result in paired:
            specialist_ids.append(agent_id)
            if result.stop_reason == "completed" and isinstance(
                result.structured, SpecialistResponse
            ):
                responses.append(result.structured)
                any_usable = True
            else:
                responses.append(_sentinel_response(agent_id))
                any_degraded = True

        sections = self._synthesizer.synthesize(
            responses, query, context, specialist_ids=specialist_ids
        )

        if not any_usable:
            status = "failure"
        elif any_degraded:
            status = "degraded"
        else:
            status = "success"
        sections["status"] = status
        return sections


__all__ = ["MacroAskExecutor"]
