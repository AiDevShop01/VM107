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


def test_combined_rag_self_acquires_without_injection(mock_agent, monkeypatch):
    """Instantiated the resolver way (NO class-attr injection), execute() returns a
    non-error combined context sourced from ``Memory.get(self.agent)`` — proving the
    self-acquire path is wired (E-HIGH1).

    The class-attr deps the runtime never sets are cleared; the local
    ``Memory.get -> db.backend.search / db._get_knowledge_v2_backend().search`` chain
    is monkeypatched to yield canned hits WITHOUT touching a real Qdrant (mirror the P4
    ``tests/phase136/test_search_knowledge_local_default.py`` harness). The live-Qdrant
    proof (real backends -> non-empty context for a grantee) runs in-container at the
    137-06 V-02 gate.

    RED before 137-06: the tool read the un-injected class-attr ``qdrant_client`` (None),
    so its graceful branch returned "No relevant context found." — it never consulted
    Memory. GREEN after the self-acquire refactor: it reads the monkeypatched backends.

    Driven via ``asyncio.run`` (pytest-asyncio is not in /opt/venv-a0 — no package
    install per the phase package-legitimacy discipline).
    """
    import plugins._memory.helpers.memory as mem_mod

    memory_hit = {
        "id": "mem-1",
        "summary": "self-acquired memory hit about liquidity regimes",
        "project": "test-project",
        "timestamp": "2026-08-10T00:00:00+00:00",
        "score": 0.81,
    }
    knowledge_hit = {
        "id": "kn-1",
        "text": "self-acquired knowledge hit: liquidity is order-book depth",
        "book_title": "Market Microstructure",
        "document_id": "42",
        "score": 0.77,
    }

    class _FakeBackend:
        def __init__(self, hits):
            self._hits = hits

        async def search(self, query, top_k, context, area=None):  # QdrantBackend.search shape
            return list(self._hits)

    class _FakeDb:
        memory_subdir = "test-project"
        context_id = "test-context"
        backend = _FakeBackend([memory_hit])

        def _get_knowledge_v2_backend(self):
            return _FakeBackend([knowledge_hit])

    async def _fake_get(agent_arg):  # Memory.get is a staticmethod(agent) — bind-free
        return _FakeDb()

    monkeypatch.setattr(mem_mod.Memory, "get", staticmethod(_fake_get), raising=True)
    monkeypatch.setattr(mem_mod, "_QdrantContext", lambda *a, **k: object(), raising=False)

    # Explicitly clear the injected class attrs the runtime never sets (supersede the
    # tests/tools/test_combined_rag.py anti-pattern) — the happy path must NOT read them.
    CombinedRAGTool.qdrant_client = None
    CombinedRAGTool.embedding_service = None
    CombinedRAGTool.ranking_config = None
    CombinedRAGTool.neo4j_driver = None

    tool = CombinedRAGTool(
        agent=mock_agent,
        name="combined_rag",
        method=None,
        args={
            "query": "what is liquidity",
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
        "combined_rag returned the empty-degradation message despite Memory.get yielding "
        "hits — self-acquire is not wired (E-HIGH1; refactor to Memory.get(self.agent))"
    )
    assert "failed" not in message.lower(), (
        f"combined_rag execute() degraded to an error message: {message!r}"
    )
    assert message.strip(), "combined_rag produced an empty response"
    # The self-acquired hits must actually surface in the combined context.
    assert (
        "liquidity" in message.lower()
    ), f"combined_rag did not surface the self-acquired hits: {message!r}"
