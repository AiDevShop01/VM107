"""E-HIGH1 — CombinedRAGTool activation (registration + self-acquire wiring).

Extends the existing ``tests/tools/test_combined_rag.py`` DI-mock harness. The existing
suite sets deps as CLASS ATTRIBUTES (``CombinedRAGTool.qdrant_client = ...``) — the very
injection the RUNTIME never performs (RESEARCH §3). This module supersedes that
anti-pattern with two RED-at-HEAD contracts:

  1. REGISTRATION — ``vm107.tool.combined_rag`` is a loadable canonical id and is
     advertised to its 8 D-06 grantees. RED today (no ``registry/tool/combined_rag.yaml``).
  2. SELF-ACQUIRE — instantiated the way the resolver does (NO class-attr injection),
     ``execute()`` returns a non-error combined context. RED today: deps are ``None`` so
     the tool's graceful branch returns "No relevant context found." (never real context).
     Goes green when 137-06 refactors ``combined_rag.py`` to self-acquire via
     ``Memory.get(self.agent)`` (mirror the P4 search_knowledge pattern) + rebuild/V-02.

The live-Qdrant proof (V-02 step 5, real ``qdrant_test_client`` -> non-empty context for a
grantee profile) lands with the 137-06 rebuild; this scaffold locks the contract.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from helpers.tool_scope import apply_tool_scope
from tools.qdrant.combined_rag import CombinedRAGTool

_PROFILE_DIR = Path(__file__).resolve().parent.parent.parent / "registry" / "agent_profile"

COMBINED_RAG_ID = "vm107.tool.combined_rag"

# D-06 narrow grantee list (RESEARCH §3 / §E-HIGH1) — purpose-fit unified memory+knowledge.
D06_GRANTEES: tuple[str, ...] = (
    "research_chat_agent",
    "vm107.chief_economist_synthesizer",
    "vm107.macro_investigator",
    "vm107.research_discovery_agent",
    "vm107.research_summarisation_agent",
    "vm107.research_citation_agent",
    "vm107.research_contrarian_agent",
    "vm107.research_classification_agent",
)


def _load_profile(profile_id: str) -> dict:
    with open(_PROFILE_DIR / f"{profile_id}.yaml") as fh:
        return yaml.safe_load(fh)


# ── Harness (mirrors tests/tools/test_combined_rag.py fixtures) ──────────────────


@pytest.fixture
def mock_agent():
    agent = Mock()
    agent.context = Mock()
    agent.context.id = "test-context"
    agent.context.project_id = "test-project"
    return agent


# ── 1. REGISTRATION (E-HIGH1) ───────────────────────────────────────────────────


def test_combined_rag_registered_as_canonical_id(reg):
    """``vm107.tool.combined_rag`` is a registered canonical capability. RED at HEAD."""
    assert reg._by_id.get(COMBINED_RAG_ID) is not None, (
        f"{COMBINED_RAG_ID!r} is not registered — add registry/tool/combined_rag.yaml "
        f"(E-HIGH1)"
    )


@pytest.mark.parametrize("grantee", D06_GRANTEES)
def test_combined_rag_advertised_to_d06_grantee(grantee, reg):
    """CombinedRAGTool is advertised to each of the 8 D-06 grantees (both surfaces)."""
    prof = _load_profile(grantee)
    index = reg.get_index_for_profile(prof["id"])
    advertised = {e["id"] for e in apply_tool_scope(
        index, prof.get("allowed_tools"), prof.get("denied_tools")
    )}
    assert COMBINED_RAG_ID in advertised, (
        f"{grantee}: {COMBINED_RAG_ID!r} must be advertised — add the tool aap grant AND "
        f"the profile allowed_tools grant (D-06, both surfaces)"
    )


# ── 2. SELF-ACQUIRE (E-HIGH1) ───────────────────────────────────────────────────


def test_combined_rag_self_acquires_without_injection(mock_agent):
    """Instantiated the resolver way (NO class-attr injection), execute() returns a
    non-error combined context — proving self-acquire is wired.

    RED at HEAD: deps are None so the graceful branch returns "No relevant context
    found." (or a contract-validation error). execute() never raises (ContractTool
    swallows), so this is a clean assertion FAILURE, not a collection/runtime error.

    Driven via ``asyncio.run`` (pytest-asyncio is not in /opt/venv-a0 — no package
    install per the phase package-legitimacy discipline).
    """
    # Explicitly clear the injected class attrs the runtime never sets (supersede the
    # tests/tools/test_combined_rag.py anti-pattern).
    CombinedRAGTool.qdrant_client = None
    CombinedRAGTool.embedding_service = None
    CombinedRAGTool.ranking_config = None
    CombinedRAGTool.neo4j_driver = None

    tool = CombinedRAGTool(
        agent=mock_agent,
        name="combined_rag",
        method=None,
        args={
            "query": "test query",
            "memory_top_k": 3,
            "knowledge_top_k": 5,
            "max_context_tokens": 2000,
            "project_id": "test-project",
        },
        message="",
        loop_data=None,
    )

    response = asyncio.run(tool.execute())
    message = getattr(response, "message", str(response))

    assert "No relevant context found" not in message, (
        "combined_rag returned the empty-degradation message with un-injected deps — "
        "self-acquire is not wired (E-HIGH1; refactor to Memory.get(self.agent) + rebuild)"
    )
    assert "failed" not in message.lower(), (
        f"combined_rag execute() degraded to an error message without injected deps "
        f"(self-acquire not wired): {message!r}"
    )
    assert message.strip(), "combined_rag produced an empty response"
