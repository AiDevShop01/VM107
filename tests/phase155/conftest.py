"""Phase 155 (VM107 router→specialist fan-out executor) Wave-0 Nyquist scaffold.

Shared fixtures the six RED test modules consume. This conftest is deliberately
import-SAFE: it imports ONLY the already-shipped contracts (``contracts.economic_intelligence``)
and NEVER the not-yet-built targets (``agents.macro_ask_executor.*``,
``contracts.economic_intelligence.subagent_contract``). Those planned modules land in
155-02/03/04, so importing them here would crash collection of the whole package — the
opposite of the intended RED-on-target signal (each test module imports its own target).

Design mirrors ``tests/phase135/conftest.py`` (repo-root bootstrap so ``agents.*`` /
``contracts.*`` resolve under the container venv) and reuses the ``_StubRegistry`` shape
from ``agents/macro_ask_router/tests/test_conversation_planner.py`` so the router the
executor drives keeps discovering the 4 pillar analysts by their canonical dotted ids.
"""
from __future__ import annotations

import os
import sys

import pytest

# ── Fail-fast env for the 155-02 PillarSnapshotFetcher (mirrors the
# domain_analyst_subscriber/tests/conftest.py precedent) ──
# ``agents.macro_ask_executor.pillar_fetcher`` reads VM100_API_URL / VM107_SERVICE_JWT at
# import time (CLAUDE.md env-driven-config lock, NO defaults). The CI host does not export
# them, so set harmless test placeholders BEFORE test_pillar_fetcher.py imports the module.
# ``setdefault`` (not ``[...] =``) so a real environment that already exports these is never
# clobbered and the fail-fast import path stays exercised in production.
os.environ.setdefault("VM100_API_URL", "http://test-vm100.local:8000")
os.environ.setdefault("VM107_SERVICE_JWT", "test-jwt-not-real")

# ── Repo-root bootstrap (copied from tests/phase135/conftest.py, PATTERNS.md L210-215) ──
# tests/phase155/ → tests/ → <repo root>. Insert so `import agents...` / `import contracts...`
# resolve to the VM107 tree regardless of the invoking interpreter's cwd.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ── The 4 pillar-analyst ids under tags [macro, specialist] (must_haves truth #2) ──
_PILLAR_AGENT_IDS: list[str] = [
    "vm107.growth_analyst",
    "vm107.inflation_analyst",
    "vm107.liquidity_analyst",
    "vm107.risk_analyst",
]

# id → PillarName map (note the risk_analyst → "RiskAppetite" asymmetry, A1 CONFIRMED).
_ID_TO_PILLAR: dict[str, str] = {
    "vm107.growth_analyst": "Growth",
    "vm107.inflation_analyst": "Inflation",
    "vm107.liquidity_analyst": "Liquidity",
    "vm107.risk_analyst": "RiskAppetite",
}


class _StubRegistry:
    """Fake Capability Registry adapter — verbatim shape from the router's own test.

    ``list_capabilities`` returns the discovery rows the router's ConversationPlanner
    consumes. Defaults to the 4 pillar analysts tagged [macro, specialist]; ``add`` lets
    a test extend the catalogue (e.g. an untagged / unknown id for the fail-loud path).
    """

    def __init__(self, agents: list[str] | None = None) -> None:
        if agents is None:
            agents = list(_PILLAR_AGENT_IDS)
        self._agents = list(agents)

    def add(self, agent_id: str) -> None:
        self._agents.append(agent_id)

    def list_capabilities(self, *, type=None, tags=None):  # noqa: A002 - mirror registry API
        return [{"id": a, "type": "agent_profile"} for a in self._agents]


@pytest.fixture
def stub_registry() -> _StubRegistry:
    """A `_StubRegistry` yielding the 4 pillar-analyst ids (macro/specialist)."""
    return _StubRegistry()


@pytest.fixture
def pillar_ids() -> list[str]:
    """The 4 canonical pillar-analyst dotted ids (fan-out target order)."""
    return list(_PILLAR_AGENT_IDS)


@pytest.fixture
def id_to_pillar() -> dict[str, str]:
    """id → PillarName map (carries the risk_analyst → RiskAppetite asymmetry)."""
    return dict(_ID_TO_PILLAR)


def _make_pillar(name: str):
    """Build a contract-valid `Pillar` for name ∈ {Growth,Inflation,Liquidity,RiskAppetite}.

    All required fields populated so construction passes under ``extra="forbid"``; the
    momentum dict is keyed EXACTLY {'1m','3m','12m'} or the Pillar validator rejects.
    """
    from contracts.economic_intelligence.pillars import Pillar, PillarState
    from contracts.economic_intelligence.provenance import ProvenanceObject

    if name not in {"Growth", "Inflation", "Liquidity", "RiskAppetite"}:
        raise ValueError(f"unknown pillar name: {name!r}")

    return Pillar(
        name=name,
        level=55.0,
        momentum={"1m": 0.5, "3m": 1.25, "12m": -0.75},  # exactly {1m,3m,12m}
        breadth=0.6,
        confidence=0.8,
        contributors=[f"vm101.indicator.{name.lower()}_composite"],
        state=PillarState.POSITIVE,
        sparkline_90d=[50.0 + (i % 5) for i in range(90)],
        provenance=ProvenanceObject(
            source_event_ids=[f"evt.{name.lower()}.001"],
            weights_version="pillar_engine@1",
            model_version="na",
            prompt_version="na",
            upstream_sections=["pillars"],
            data_versions={"vm101.economic_event": 12},
        ),
    )


@pytest.fixture
def pillar_factory():
    """Callable `make_pillar(name)` → a contract-valid `Pillar` for each pillar name."""
    return _make_pillar


class _StubPillarFetcher:
    """Stub pillar fetcher: returns a Pillar for known names, None for a degraded name.

    ``degraded`` names a pillar deliberately flagged unavailable (e.g. "Liquidity") so the
    executor's honest-degradation branch has an injectable transient miss without touching
    the real dashboard read path.
    """

    def __init__(self, degraded: str | None = None) -> None:
        self._degraded = degraded

    def get(self, pillar_name: str, country: str = "US"):
        if pillar_name == self._degraded:
            return None
        if pillar_name not in {"Growth", "Inflation", "Liquidity", "RiskAppetite"}:
            return None
        return _make_pillar(pillar_name)


@pytest.fixture
def stub_pillar_fetcher():
    """Factory `make_fetcher(degraded=None)` → a stub fetcher (None for the degraded name)."""

    def _make(degraded: str | None = None) -> _StubPillarFetcher:
        return _StubPillarFetcher(degraded=degraded)

    return _make


@pytest.fixture
def fake_plan():
    """Callable building a router Plan dict the executor consumes.

    Shape: {required_agents, execution_order, expected_latency, reasoning}. Defaults to the
    inflation+growth cross-pillar plan; callers override any field (e.g. required_agents=[]
    to exercise the empty-plan fail-loud path, or execution_order="sequential").
    """

    def _make(
        *,
        required_agents: list[str] | None = None,
        execution_order: str = "parallel",
        expected_latency: float = 1.5,
        reasoning: str = "stub plan",
    ) -> dict:
        if required_agents is None:
            required_agents = [
                "vm107.inflation_analyst",
                "vm107.growth_analyst",
            ]
        return {
            "required_agents": list(required_agents),
            "execution_order": execution_order,
            "expected_latency": expected_latency,
            "reasoning": reasoning,
        }

    return _make
