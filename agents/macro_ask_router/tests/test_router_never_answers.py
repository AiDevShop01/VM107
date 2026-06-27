"""Phase 94-06 — MacroAskRouter pure-classifier tests (§J).

The router is a CLASSIFIER. It returns an execution plan and NEVER an
answer. Static-grep guards enforce no LLM imports in the agent source.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from agents.macro_ask_router import MacroAskRouter
from agents.macro_ask_router import agent as agent_module


class _StubRegistry:
    """Minimal stand-in for the Phase 47.6 lookup_capability list view."""

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

    def list_capabilities(self, *, type=None, tags=None):
        return [{"id": a, "type": "agent_profile"} for a in self._agents]


def test_router_returns_plan_not_answer():
    router = MacroAskRouter(_StubRegistry())
    out = router.invoke("Why is inflation cooling?")
    # Required keys per §J.
    assert "required_agents" in out
    assert "execution_order" in out
    assert "expected_latency" in out
    # Forbidden keys.
    assert "answer" not in out, "router must NEVER return an 'answer' key (§J)"
    # If a free-text field exists it must be the short reasoning trace — not prose.
    if "reasoning" in out:
        assert len(out["reasoning"]) <= 200, "reasoning must be short trace, not prose"


def test_router_routes_inflation_query_to_inflation_analyst():
    router = MacroAskRouter(_StubRegistry())
    out = router.invoke("Why is CPI cooling?")
    assert "vm107.inflation_analyst" in out["required_agents"]


def test_router_routes_central_bank_query_to_central_bank_summariser():
    router = MacroAskRouter(_StubRegistry())
    out = router.invoke("Was the Fed hawkish today?")
    assert "vm107.central_bank_summariser" in out["required_agents"]


def test_router_empty_query_returns_empty_plan():
    router = MacroAskRouter(_StubRegistry())
    out = router.invoke("")
    assert out["required_agents"] == []


def _executable_lines(src: str) -> list[str]:
    """Return only the non-comment, non-docstring source lines (best-effort).

    Strips triple-quoted blocks and ``#`` comments so the static guard
    matches actual ``import`` statements rather than mentions in docstrings.
    """
    out: list[str] = []
    in_doc = False
    doc_marker: str | None = None
    for line in src.splitlines():
        stripped = line.strip()
        if in_doc:
            if doc_marker and doc_marker in line:
                in_doc = False
                doc_marker = None
            continue
        if stripped.startswith('"""') or stripped.startswith("'''"):
            marker = '"""' if stripped.startswith('"""') else "'''"
            # Same-line docstring close?
            if stripped.count(marker) >= 2:
                continue  # single-line docstring, skip
            in_doc = True
            doc_marker = marker
            continue
        # Strip trailing comment.
        if "#" in line:
            # naive but adequate — split at first ``#`` not inside quotes.
            line = line.split("#", 1)[0]
        out.append(line)
    return out


def test_static_grep_for_answer_emission():
    """Source guard: macro_ask_router/agent.py + conversation_planner.py
    must NOT import any LLM client (openai/anthropic/langchain/llamaindex).

    Mentions in docstrings/comments are fine — only actual `import` lines fail."""
    src = Path(inspect.getfile(agent_module)).read_text()
    planner_mod = __import__(
        "agents.macro_ask_router.conversation_planner", fromlist=["x"]
    )
    planner_src = Path(inspect.getfile(planner_mod)).read_text()

    agent_executable = "\n".join(_executable_lines(src))
    planner_executable = "\n".join(_executable_lines(planner_src))

    banned = (
        "import openai",
        "from openai",
        "import anthropic",
        "from anthropic",
        "import langchain",
        "from langchain",
        "import llamaindex",
        "from llamaindex",
        "from llama_index",
        "import llama_index",
    )
    for needle in banned:
        assert needle not in agent_executable, (
            f"router agent.py imports LLM client at module scope: {needle!r}"
        )
        assert needle not in planner_executable, (
            f"router conversation_planner.py imports LLM client at module scope: {needle!r}"
        )


def test_router_classifier_fallback_is_injected_not_imported():
    """Router accepts an injected classifier; passing None uses a NULL stub
    (returns empty list). No magic LLM import at planner construction time."""
    # Default (no classifier) — registry empty → empty plan.
    router = MacroAskRouter(_StubRegistry(agents=[]))
    out = router.invoke("what should I do about my portfolio")
    assert out["required_agents"] == []

    # With injected classifier — must populate required_agents.
    def fake_classifier(q, options):
        return ["vm107.growth_analyst"] if "portfolio" in q else []

    router2 = MacroAskRouter(_StubRegistry(), llm_classifier=fake_classifier)
    out2 = router2.invoke("what should I do about my portfolio")
    assert "vm107.growth_analyst" in out2["required_agents"]
