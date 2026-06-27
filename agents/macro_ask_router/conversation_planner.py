"""Phase 94-06 — ConversationPlanner (hybrid heuristic + registry-driven).

The planner returns an execution plan describing **which specialists** to
invoke and **in what order**, given a user query and optional dashboard
context. It does NOT call any LLM for ANSWERS — only (optionally) for
intent classification fallback when heuristics fail.

Three-tier strategy per CONTEXT.md (Claude's Discretion):

1. **Heuristic pass** — keyword-to-specialist mapping covers the high-
   intent macro vocabulary (inflation, growth, central bank, forecast,
   liquidity, risk, compare-X-vs-Y).
2. **Capability Registry discovery** — :func:`list_capabilities` ensures
   newly-registered specialists are picked up without code change (per
   §J anti-pattern: no hardcoded specialist list).
3. **LLM-classifier fallback** — only invoked when the heuristic + registry
   path returns no specialist; uses a small/cheap classifier model. The
   classifier is INJECTED so unit tests pass a stub.

The plan return shape is intentionally narrow:

    Plan(required_agents: list[str], execution_order: str,
         expected_latency_seconds: float, reasoning: str)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Protocol


# ─────────────────────────────────────────────────────────── plan shape


@dataclass(frozen=True)
class Plan:
    """Routing plan returned by the planner.

    Note: `answer` is INTENTIONALLY ABSENT — the router is a pure
    classifier per §J. The chief_economist_synthesizer composes the
    natural-language answer from specialist outputs.
    """

    required_agents: list[str]
    execution_order: str        # "parallel" | "sequential"
    expected_latency_seconds: float
    reasoning: str


# ─────────────────────────────────────────────────────────── registry abstraction


class CapabilityRegistryProtocol(Protocol):
    """Subset of the Phase 47.6 lookup_capability API the planner uses."""

    def list_capabilities(
        self,
        *,
        type: str | None = None,
        tags: list[str] | None = None,
    ) -> list[dict]:
        ...


# ─────────────────────────────────────────────────────────── heuristic mapping
#
# Keyword → specialist agent_id. Vocabulary covers the high-traffic
# macro-intelligence intents per CONTEXT.md §J. Extend by adding rows;
# the planner picks the FIRST match per query token to avoid duplicate
# specialist invocations. Registry-discovery (below) supplements this with
# any new specialist registered post-ship.

_HEURISTIC_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("inflation", "cpi", "ppi", "pce", "deflation", "disinflation"),
     "vm107.inflation_analyst"),
    (("growth", "gdp", "payroll", "payems", "ism", "pmi"),
     "vm107.growth_analyst"),
    (("liquidity", "balance sheet", "qt", "qe", "credit", "spread"),
     "vm107.liquidity_analyst"),
    (("risk", "risk appetite", "vix", "volatility", "drawdown", "stress"),
     "vm107.risk_analyst"),
    (("fed", "ecb", "boj", "boe", "central bank", "rate decision", "hawkish", "dovish"),
     "vm107.central_bank_summariser"),
    (("forecast", "predict", "consensus", "outlook"),
     "vm107.macro_forecast_narrator"),
    (("theme", "themes", "regime shift", "structural"),
     "vm107.theme_monitor"),
)


def _heuristic_match(query: str) -> list[str]:
    """Return UNIQUE specialist ids that match the query keywords (preserving order)."""
    q = query.lower()
    matched: list[str] = []
    seen: set[str] = set()
    for keywords, agent_id in _HEURISTIC_RULES:
        if any(kw in q for kw in keywords):
            if agent_id not in seen:
                matched.append(agent_id)
                seen.add(agent_id)
    return matched


def _is_compare_query(query: str) -> bool:
    q = query.strip().lower()
    return q.startswith("compare ") or " vs " in q or " versus " in q


# ─────────────────────────────────────────────────────────── planner


class ConversationPlanner:
    """Hybrid heuristic + capability-registry + LLM-classifier-fallback router."""

    DEFAULT_LATENCY_SECONDS = 8.0
    PER_AGENT_BUDGET_SECONDS = 1.5

    def __init__(
        self,
        capability_registry: CapabilityRegistryProtocol,
        llm_classifier: Callable[[str, list[str]], list[str]] | None = None,
    ) -> None:
        self._registry = capability_registry
        # Injected for tests; default is a NULL classifier that returns an
        # empty list (callers see "no specialist found" cleanly).
        self._classifier = llm_classifier or (lambda _q, _options: [])

    # ------------------------------------------------------------------ public
    def plan(self, *, query: str, dashboard_context: dict | None = None) -> Plan:
        if not query or not query.strip():
            return Plan(
                required_agents=[],
                execution_order="parallel",
                expected_latency_seconds=0.0,
                reasoning="empty query — nothing to route",
            )

        context = dashboard_context or {}
        available = self._discover_specialists()

        # 1) Heuristic pass.
        heuristic_hits = [a for a in _heuristic_match(query) if a in available]

        # Context-aware cross-pillar expansion — if the user is on a specific
        # pillar but asks about another, include both for cross-pillar context.
        selected_pillar = context.get("selected_pillar")
        if selected_pillar and heuristic_hits:
            pillar_to_agent = {
                "Inflation": "vm107.inflation_analyst",
                "Growth": "vm107.growth_analyst",
                "Liquidity": "vm107.liquidity_analyst",
                "RiskAppetite": "vm107.risk_analyst",
            }
            pillar_agent = pillar_to_agent.get(selected_pillar)
            if pillar_agent and pillar_agent in available and pillar_agent not in heuristic_hits:
                heuristic_hits.append(pillar_agent)

        # "compare" intent — request country_intelligence_agent forward-link
        # so 96 can drop in without router edits. If not yet registered, we
        # only add it if the registry surfaces it.
        if _is_compare_query(query):
            cia = "vm107.country_intelligence_agent"
            if cia in available and cia not in heuristic_hits:
                heuristic_hits.insert(0, cia)

        if heuristic_hits:
            return Plan(
                required_agents=heuristic_hits,
                execution_order="parallel" if len(heuristic_hits) > 1 else "sequential",
                expected_latency_seconds=self._estimate_latency(heuristic_hits),
                reasoning=f"heuristic match on {len(heuristic_hits)} specialist(s)",
            )

        # 2) Registry-driven fallback — list all specialists and let the
        # LLM classifier (or a hard-coded "pick first" stub) choose.
        if available:
            picked = self._classifier(query, available)
            picked = [a for a in picked if a in available]
            if picked:
                return Plan(
                    required_agents=picked,
                    execution_order="parallel" if len(picked) > 1 else "sequential",
                    expected_latency_seconds=self._estimate_latency(picked),
                    reasoning="llm-classifier fallback on registry catalogue",
                )

        # 3) Nothing matched — return empty plan; caller decides how to surface.
        return Plan(
            required_agents=[],
            execution_order="parallel",
            expected_latency_seconds=0.0,
            reasoning="no heuristic match and no classifier hit",
        )

    # ---------------------------------------------------------------- internals
    def _discover_specialists(self) -> list[str]:
        """Use Phase 47.6 registry to enumerate macro specialists.

        Never hardcode the list — adding a new specialist requires only a new
        agent_profile YAML with tag 'specialist' (or both 'macro' + 'specialist').
        """
        results = self._registry.list_capabilities(
            type="agent_profile",
            tags=["macro", "specialist"],
        )
        return [r["id"] for r in results if "id" in r]

    def _estimate_latency(self, agents: Iterable[str]) -> float:
        # Parallel: bounded by the slowest (per-agent budget). Sequential: sum.
        n = sum(1 for _ in agents)
        if n == 0:
            return 0.0
        # Conservative bound — use per-agent budget × N for sequential, otherwise
        # the per-agent budget. Plus synthesizer overhead.
        per_agent = self.PER_AGENT_BUDGET_SECONDS
        if n == 1:
            return per_agent + 1.0
        return per_agent + 1.0  # parallel — bounded by slowest specialist


__all__ = ["ConversationPlanner", "Plan", "CapabilityRegistryProtocol"]
