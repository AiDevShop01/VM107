"""
Phase 44 Plan 03 — Envelope persistence integration tests (graduated from xfail stubs).

Tests that AgentEnvelope documents are written to MongoDB agent_envelopes collection
with correct fields. Uses an in-memory FakeDB instead of mongomock (not installed)
or real MongoDB (not required for unit-level integration tests).

xfail markers removed — all tests are concrete GREEN passes.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest
from core.contracts.schemas import Hypothesis, StrategySpec, StrategyFamily


# ---------------------------------------------------------------------------
# In-memory FakeDB — enough for envelope persistence tests without mongomock
# ---------------------------------------------------------------------------

class FakeCollection:
    """Minimal in-memory MongoDB collection double.

    Supports: insert_one, find_one, count_documents, create_index,
    list_collection_names (via FakeDatabase).
    """

    def __init__(self) -> None:
        self._docs: list[dict] = []
        self._indexes: list[tuple] = []  # list of (key_list, options)

    def insert_one(self, doc: dict) -> None:
        """Append doc to internal list. _id must be set by caller."""
        self._docs.append(dict(doc))

    def find_one(self, query: dict) -> dict | None:
        """Return first document matching ALL query key=value pairs. None if not found."""
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None

    def find(self, query: dict | None = None) -> list[dict]:
        """Return all docs (no filter support needed for these tests)."""
        return [dict(d) for d in self._docs]

    def count_documents(self, query: dict | None = None) -> int:
        """Return total document count (query ignored — not needed for these tests)."""
        return len(self._docs)

    def create_index(self, key_list: Any, **kwargs: Any) -> str:
        """Record index creation. Returns a fake index name."""
        self._indexes.append((key_list, kwargs))
        name = kwargs.get("name", f"idx_{len(self._indexes)}")
        return name


class FakeDatabase:
    """Minimal in-memory MongoDB database double."""

    def __init__(self) -> None:
        self._collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self._collections:
            self._collections[name] = FakeCollection()
        return self._collections[name]

    def create_collection(self, name: str) -> FakeCollection:
        if name not in self._collections:
            self._collections[name] = FakeCollection()
        return self._collections[name]

    def list_collection_names(self) -> list[str]:
        return list(self._collections.keys())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_db() -> FakeDatabase:
    """Fresh in-memory FakeDatabase for each test."""
    return FakeDatabase()


@pytest.fixture
def valid_hypothesis() -> Hypothesis:
    return Hypothesis(
        hypothesis="momentum tends to persist in trending markets",
        variables=["rsi_14", "ema_20"],
        confidence=0.7,
    )


@pytest.fixture
def valid_strategy_json() -> str:
    return StrategySpec(
        name="Momentum Trend",
        features=["rsi_14", "ema_20"],
        rules=["rsi > 60"],
        timeframes=["1h"],
        version="1.0.0",
        strategy_family=StrategyFamily.TREND_CONTINUATION,
    ).model_dump_json()


@pytest.fixture
def valid_hypothesis_json(valid_hypothesis: Hypothesis) -> str:
    return valid_hypothesis.model_dump_json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_envelope_written_success(fake_db, valid_hypothesis, valid_strategy_json):
    """
    Successful run_strategy invocation writes one AgentEnvelope with status=success.

    Asserts:
      - Exactly one document inserted to agent_envelopes
      - doc["status"] == "success"
      - doc["agent_id"] == "strategy_agent"
      - doc["_id"] == doc["envelope_id"] (Phase 43.2 convention)
    """
    from core.agents.invocation import run_strategy

    with patch("core.agents.invocation._call_subordinate_sync", return_value=valid_strategy_json):
        result = run_strategy(valid_hypothesis, db=fake_db)

    col = fake_db["agent_envelopes"]
    assert col.count_documents() == 1

    doc = col._docs[0]
    assert doc["status"] == "success"
    assert doc["agent_id"] == "strategy_agent"
    assert doc["_id"] == doc["envelope_id"]
    assert doc["envelope_id"]  # non-empty string


def test_envelope_written_failure(fake_db, valid_hypothesis):
    """
    Failed invocation (both attempts degrade) writes two rows with status=degraded.

    Per CONTEXT.md § Failure Handling:
      - Each attempt (initial + retry) writes its own envelope with status=degraded
      - After raise, NO additional success/failure row
    """
    from core.agents.invocation import run_strategy
    from core.agents.invocation_exceptions import StrategyAgentDegradedError

    degraded_response = "I cannot structure this output."

    with patch("core.agents.invocation._call_subordinate_sync", return_value=degraded_response):
        with pytest.raises(StrategyAgentDegradedError):
            run_strategy(valid_hypothesis, db=fake_db)

    col = fake_db["agent_envelopes"]
    # Exactly 2 rows — one per attempt (initial + retry)
    assert col.count_documents() == 2
    for doc in col._docs:
        assert doc["status"] == "degraded"
        assert doc["agent_id"] == "strategy_agent"


def test_chain_provenance(fake_db, valid_hypothesis, valid_hypothesis_json, valid_strategy_json):
    """
    Idea envelope_id (X) appears as Strategy envelope's source_envelope_id.

    Full provenance chain: run_idea → Hypothesis(source_envelope_id=X) → run_strategy
    Strategy envelope must have source_envelope_id == X.

    Per CONTEXT.md § A2A Envelope Structure:
      'source_envelope_id: explicit reference — NOT implicit find-latest-under-task_id.'
    """
    from core.agents.invocation import run_idea, run_strategy

    # Both mocks return a valid JSON response
    call_returns = [valid_hypothesis_json, valid_strategy_json]
    call_index = [0]

    def side_effect(*args, **kwargs):
        i = call_index[0]
        call_index[0] += 1
        return call_returns[i]

    with patch("core.agents.invocation._call_subordinate_sync", side_effect=side_effect):
        hypothesis = run_idea("design a strategy for momentum", db=fake_db)
        strategy_spec = run_strategy(hypothesis, db=fake_db)

    col = fake_db["agent_envelopes"]
    assert col.count_documents() >= 2

    # Idea envelope exists with agent_id=idea_agent
    idea_doc = col.find_one({"agent_id": "idea_agent"})
    assert idea_doc is not None
    idea_env_id = idea_doc["envelope_id"]

    # hypothesis has source_envelope_id linked to Idea envelope
    assert hypothesis.source_envelope_id == idea_env_id

    # Strategy envelope has source_envelope_id == Idea envelope_id
    strategy_doc = col.find_one({"agent_id": "strategy_agent"})
    assert strategy_doc is not None
    assert strategy_doc["source_envelope_id"] == idea_env_id


def test_envelope_id_is_uuid_str(fake_db, valid_hypothesis, valid_strategy_json):
    """Every persisted envelope's _id is a 36-char UUID string."""
    from core.agents.invocation import run_strategy

    with patch("core.agents.invocation._call_subordinate_sync", return_value=valid_strategy_json):
        run_strategy(valid_hypothesis, db=fake_db)

    col = fake_db["agent_envelopes"]
    for doc in col._docs:
        _id = doc["_id"]
        assert isinstance(_id, str), f"_id must be str, got {type(_id)}"
        assert len(_id) == 36, f"_id must be 36-char UUID, got len={len(_id)}: {_id!r}"
        # Basic UUID format validation: 8-4-4-4-12 sections
        parts = _id.split("-")
        assert len(parts) == 5, f"UUID must have 5 hyphen-separated parts: {_id!r}"
        assert [len(p) for p in parts] == [8, 4, 4, 4, 12], f"UUID segment lengths wrong: {_id!r}"


def test_envelope_indexes(fake_db):
    """
    Migration 007 up() creates the 4 expected indexes on agent_envelopes.

    Per CONTEXT.md § A2A Envelope Structure:
      Indexes: task_id, source_envelope_id, agent_id+timestamp, timestamp

    Uses importlib to load the migration script directly (file-name starts with 007_
    so it cannot be imported as a standard Python package path).
    """
    import importlib.util

    migration_path = _VM107_ROOT / "core" / "migrations" / "scripts" / "007_agent_envelopes.py"
    spec = importlib.util.spec_from_file_location("migration_007", str(migration_path))
    assert spec is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)  # type: ignore[union-attr]

    migration.up(fake_db)

    col = fake_db["agent_envelopes"]
    # Verify 4 indexes were created
    assert len(col._indexes) == 4, f"Expected 4 indexes, got {len(col._indexes)}"

    index_names = {kwargs.get("name", "") for _, kwargs in col._indexes}
    expected_names = {
        "task_id_1",
        "source_envelope_id_1",
        "agent_id_1_timestamp_-1",
        "timestamp_-1",
    }
    assert expected_names.issubset(index_names), (
        f"Expected index names {expected_names}, found {index_names}"
    )


