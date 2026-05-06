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


# ================================================================
# PHASE 47.1 ADDITIONS — Wave 0 evaluation runner fixtures
# ================================================================

@pytest.fixture
def mock_evaluation_llm():
    """AsyncMock factory for the evaluation LLM call.

    Returns an AsyncMock configured to return a canned valid JSON string
    matching the PreTradeEvaluation schema on the first call.

    To parametrise for retry-once-then-fail tests:
        mock_evaluation_llm.side_effect = [PlainTextResult_instance, valid_json_str]

    Usage in tests:
        with patch("core.agents.evaluation_runner._call_llm_structured",
                   new=mock_evaluation_llm):
            result = await run_pre_trade_evaluation(...)
    """
    import json as _json

    canned_valid_json = _json.dumps({
        "recommendation": "enter",
        "confidence": 0.82,
        "score": 74,
        "max_score": 100,
        "direction": "long",
        "instrument": "XAUUSD",
        "check_results": {
            "htf_alignment": "pass",
            "compression_pause": "pass",
            "displacement_candle": "unclear",
            "location_quality": "pass",
            "rr_acceptable": "pass",
        },
        "reasoning_summary": "Strong HTF alignment with clean displacement. Location quality confirmed.",
        "risks": ["Upcoming NFP data could reverse momentum", "Spread widening near session open"],
        "invalidations": ["Price closes below 2618 structure low", "HTF bearish shift confirmed"],
        "next_action": "Enter at 2625 limit, SL 2612, TP 2645. Risk 1%.",
    })

    mock = AsyncMock(return_value=canned_valid_json)
    return mock


@pytest.fixture
def mock_eval_db():
    """MagicMock MongoDB double for evaluation runner tests.

    Exposes db["agent_envelopes"] with find(), find_one(), insert_one() configured.

    Backed by an in-memory list so tests can assert on call args without a
    real MongoDB connection. Compatible with the mock_mongo_client pattern
    (Phase 44) but extended for evaluation history queries.

    Usage:
        with patch("core.agents.evaluation_runner.get_mongo_db",
                   return_value=mock_eval_db):
            result = await run_pre_trade_evaluation(...)
        # Assert history was queried:
        mock_eval_db["agent_envelopes"].find.assert_called_once_with(...)
    """
    history_docs: list = []
    inserted_docs: list = []

    envelopes_col = MagicMock()
    envelopes_col.find.return_value = iter(history_docs)
    envelopes_col.find_one.return_value = None
    envelopes_col.insert_one.side_effect = lambda doc: inserted_docs.append(doc)
    envelopes_col._history_docs = history_docs
    envelopes_col._inserted_docs = inserted_docs

    db = MagicMock()
    db.__getitem__ = MagicMock(
        side_effect=lambda name: envelopes_col if name == "agent_envelopes" else MagicMock()
    )
    return db
