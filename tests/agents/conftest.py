"""Conftest for tests/agents/ — mirrors tests/routing/conftest.py path setup.

Phase 44 additions:
- mock_agent_context: minimal AgentContext-like stub for Agent Zero DI
- mock_mongo_client: in-memory dict double exposing db["agent_envelopes"]
- valid_hypothesis: Hypothesis fixture used by invocation + tool-scope tests
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# VM107 root is grandparent of this conftest (tests/agents/conftest.py -> tests/agents -> tests -> VM107)
_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

from core.contracts.schemas import Hypothesis


@pytest.fixture
def mock_agent_context():
    """
    Minimal AgentContext-like stub for Agent Zero dependency injection.

    Provides get_data/set_data simulation using an internal dict, plus
    agent_name and config.profile attributes used by tool scope checks.
    """
    ctx = MagicMock()
    ctx._data = {}
    ctx.agent_name = "A0"
    ctx.config = MagicMock()
    ctx.config.profile = "agent0"
    ctx.get_data.side_effect = lambda k, d=None: ctx._data.get(k, d)
    ctx.set_data.side_effect = lambda k, v: ctx._data.update({k: v})
    return ctx


@pytest.fixture
def mock_mongo_client():
    """
    In-memory MongoDB double exposing db["agent_envelopes"].

    Backed by a plain list so tests can assert on inserted documents without
    a real MongoDB connection. insert_one() appends to inserted_docs.
    find() returns an iterator over inserted_docs (no filter support).
    """
    inserted_docs: list = []

    col = MagicMock()
    col.inserted_docs = inserted_docs
    col.insert_one.side_effect = lambda doc: inserted_docs.append(doc)
    col.find.return_value = iter(inserted_docs)

    db = MagicMock()
    db.__getitem__ = MagicMock(side_effect=lambda name: col if name == "agent_envelopes" else MagicMock())
    return db


@pytest.fixture
def valid_hypothesis():
    """Minimal valid Hypothesis for use in invocation and tool-scope tests."""
    return Hypothesis(
        hypothesis="momentum tends to persist in trending markets",
        variables=["rsi_14", "ema_20"],
        confidence=0.7,
    )
