"""
Phase 44 Plan 04 — Strategy endpoint integration tests (graduated from xfail stubs).

Tests POST /api/v1/agents/strategy/invoke via Flask test client.

Uses Flask test client with register_api_route (file-based dispatch) to exercise
the full StrategyInvoke handler with mocked subordinate dependencies:
  - helpers.settings.get_settings → injects test API key
  - api.v1.agents.strategy.invoke._get_db → FakeDB (no real MongoDB)
  - core.agents.invocation.run_strategy → mocked (no real LLM)

Test names match 44-VALIDATION.md "Per-Task Verification Map" exactly.
"""
from __future__ import annotations

import json
import sys
import threading
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

import pytest
from flask import Flask

from core.contracts.schemas import Hypothesis, StrategySpec
from core.agents.invocation_exceptions import StrategyAgentDegradedError

# Force the endpoint module into sys.modules under its dotted path so that
# unittest.mock.patch("api.v1.agents.strategy.invoke.*") resolves correctly.
# load_classes_from_file uses spec_from_file_location with a bare name ("invoke"),
# which does NOT register under the full dotted path. Importing directly here fixes that.
import importlib, importlib.util as _ilu
_invoke_spec = _ilu.spec_from_file_location(
    "api.v1.agents.strategy.invoke",
    str(_VM107_ROOT / "api" / "v1" / "agents" / "strategy" / "invoke.py"),
)
_invoke_module = importlib.util.module_from_spec(_invoke_spec)
import sys as _sys
_sys.modules.setdefault("api.v1.agents.strategy.invoke", _invoke_module)
_invoke_spec.loader.exec_module(_invoke_module)


# ---------------------------------------------------------------------------
# In-memory FakeDB (reuse pattern from test_envelope_persistence.py)
# ---------------------------------------------------------------------------

class FakeCollection:
    """Minimal in-memory MongoDB collection double.

    Supports insert_one, find_one (with optional sort kwarg ignored), count_documents.
    """

    def __init__(self) -> None:
        self._docs: list[dict] = []

    def insert_one(self, doc: dict) -> None:
        self._docs.append(dict(doc))

    def find_one(self, query: dict, **kwargs) -> dict | None:
        """Return first document matching ALL query key=value pairs. None if not found."""
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None

    def count_documents(self, query: dict | None = None) -> int:
        return len(self._docs)


class FakeDatabase:
    """Minimal in-memory MongoDB database double."""

    def __init__(self) -> None:
        self._collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self._collections:
            self._collections[name] = FakeCollection()
        return self._collections[name]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_API_KEY = "test-api-key-phase44"


@pytest.fixture
def fake_db() -> FakeDatabase:
    """Fresh FakeDB for each test."""
    return FakeDatabase()


@pytest.fixture
def flask_app(fake_db) -> Flask:
    """Minimal Flask app with register_api_route wired.

    Patches:
      - helpers.settings.get_settings → returns test API key
      - api.v1.agents.strategy.invoke._get_db → returns fake_db

    Both patches stay active for the lifetime of the app fixture so they cover
    the request/response cycle inside the test client context manager.
    """
    app = Flask("test_strategy_endpoint")
    app.secret_key = "test-secret"

    lock = threading.RLock()

    from helpers.api import register_api_route
    register_api_route(app, lock)

    app.testing = True
    return app


def _valid_hypothesis_dict() -> dict:
    return {
        "hypothesis": "momentum tends to persist in trending markets",
        "variables": ["rsi_14", "ema_20"],
        "confidence": 0.75,
        "schema_version": 1,
    }


def _valid_strategy_spec() -> StrategySpec:
    return StrategySpec(
        name="Momentum Trend",
        features=["rsi_14", "ema_20"],
        rules=["rsi > 60"],
        timeframes=["1h"],
        version="1.0.0",
    )


def _make_envelope_doc(task_id: str) -> dict:
    """Build a fake envelope document that the endpoint queries after run_strategy."""
    eid = str(uuid.uuid4())
    return {
        "_id": eid,
        "envelope_id": eid,
        "task_id": task_id,
        "agent_id": "strategy_agent",
        "status": "success",
        "model_used": "deepseek/deepseek-v4-flash",
        "fallback_used": False,
    }


# ---------------------------------------------------------------------------
# Tests (graduated from xfail stubs)
# ---------------------------------------------------------------------------

def test_sync_success(flask_app, fake_db):
    """
    POST /api/v1/agents/strategy/invoke with valid Hypothesis returns 200 + StrategySpec body.

    Response must contain strategy_spec dict and meta block with envelope_id,
    source_envelope_id, agent_id, model_used, fallback_used, duration_ms.
    Graduated from Plan 44-04 Task 1.
    """
    def mock_run_strategy(hypothesis, *, db=None, task_id=None, **kwargs):
        # Capture task_id and seed FakeDB so endpoint find_one finds the envelope
        if task_id and db is not None:
            doc = _make_envelope_doc(task_id)
            db["agent_envelopes"].insert_one(doc)
        return _valid_strategy_spec()

    settings_mock = MagicMock(return_value={"mcp_server_token": TEST_API_KEY})

    with patch("helpers.settings.get_settings", settings_mock), \
         patch("helpers.mongo.get_mongo_db", return_value=fake_db), \
         patch("core.agents.invocation.run_strategy", side_effect=mock_run_strategy):

        client = flask_app.test_client()
        resp = client.post(
            "/api/v1/agents/strategy/invoke",
            json={"hypothesis": _valid_hypothesis_dict()},
            headers={"X-API-KEY": TEST_API_KEY},
        )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.data}"
    body = json.loads(resp.data)

    assert "strategy_spec" in body, f"Missing strategy_spec in {body}"
    assert "meta" in body, f"Missing meta in {body}"

    meta = body["meta"]
    assert "envelope_id" in meta
    assert meta["agent_id"] == "strategy_agent"
    assert isinstance(meta["fallback_used"], bool)
    assert isinstance(meta["duration_ms"], int)
    # source_envelope_id may be None (no upstream Idea Agent in this test)
    assert "source_envelope_id" in meta


def test_invalid_hypothesis(flask_app, fake_db):
    """
    POST with malformed hypothesis JSON returns 422 Unprocessable Entity.

    Endpoint must validate Hypothesis with model_validate() BEFORE invoking agent.
    Graduated from Plan 44-04 Task 1.
    """
    settings_mock = MagicMock(return_value={"mcp_server_token": TEST_API_KEY})

    with patch("helpers.settings.get_settings", settings_mock), \
         patch("helpers.mongo.get_mongo_db", return_value=fake_db):

        client = flask_app.test_client()
        # Missing required fields: variables, confidence
        resp = client.post(
            "/api/v1/agents/strategy/invoke",
            json={"hypothesis": {"hypothesis": ""}},
            headers={"X-API-KEY": TEST_API_KEY},
        )

    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.data}"
    body = json.loads(resp.data)
    assert "error" in body


def test_schema_version_mismatch(flask_app, fake_db):
    """
    POST Hypothesis with schema_version: 2 returns 422 + SchemaVersionMismatchError detail.

    Strict fail-fast per CONTEXT.md § A2A Envelope Structure — no implicit migration.
    Graduated from Plan 44-04 Task 1.
    """
    settings_mock = MagicMock(return_value={"mcp_server_token": TEST_API_KEY})

    with patch("helpers.settings.get_settings", settings_mock), \
         patch("helpers.mongo.get_mongo_db", return_value=fake_db):

        client = flask_app.test_client()
        resp = client.post(
            "/api/v1/agents/strategy/invoke",
            json={"hypothesis": {
                "hypothesis": "momentum tends to persist in trending markets",
                "variables": ["rsi_14"],
                "confidence": 0.7,
                "schema_version": 2,  # version mismatch — expect 422
            }},
            headers={"X-API-KEY": TEST_API_KEY},
        )

    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.data}"
    body = json.loads(resp.data)
    assert "SchemaVersionMismatchError" in body.get("error", ""), (
        f"Expected SchemaVersionMismatchError in error field, got: {body}"
    )


def test_agent_failure(flask_app, fake_db):
    """
    POST where run_strategy raises StrategyAgentDegradedError returns 502 Bad Gateway.

    A status=failure AgentEnvelope must be persisted.
    Graduated from Plan 44-04 Task 1.
    """
    settings_mock = MagicMock(return_value={"mcp_server_token": TEST_API_KEY})

    def mock_run_strategy_fail(hypothesis, *, db=None, task_id=None, **kwargs):
        raise StrategyAgentDegradedError(
            error_chain=["attempt_1_degraded", "attempt_2_degraded"]
        )

    with patch("helpers.settings.get_settings", settings_mock), \
         patch("helpers.mongo.get_mongo_db", return_value=fake_db), \
         patch("core.agents.invocation.run_strategy", side_effect=mock_run_strategy_fail):

        client = flask_app.test_client()
        resp = client.post(
            "/api/v1/agents/strategy/invoke",
            json={"hypothesis": _valid_hypothesis_dict()},
            headers={"X-API-KEY": TEST_API_KEY},
        )

    assert resp.status_code == 502, f"Expected 502, got {resp.status_code}: {resp.data}"
    body = json.loads(resp.data)
    assert "error" in body
    assert "envelope_id" in body

    # Verify status=failure envelope was persisted to FakeDB
    col = fake_db["agent_envelopes"]
    assert col.count_documents() >= 1, "Expected at least one envelope persisted"
    failure_doc = col.find_one({"status": "failure"})
    assert failure_doc is not None, (
        f"Expected status=failure doc in agent_envelopes, found: {col._docs}"
    )
    assert failure_doc["agent_id"] == "strategy_agent"


def test_async_mode(flask_app, fake_db):
    """
    POST ?async=true returns 202 Accepted + {"task_id": ...} body.

    task_id should be a non-empty string. run_strategy is NOT called.
    Graduated from Plan 44-04 Task 1.
    """
    settings_mock = MagicMock(return_value={"mcp_server_token": TEST_API_KEY})
    run_strategy_mock = MagicMock()

    with patch("helpers.settings.get_settings", settings_mock), \
         patch("helpers.mongo.get_mongo_db", return_value=fake_db), \
         patch("core.agents.invocation.run_strategy", run_strategy_mock):

        client = flask_app.test_client()
        resp = client.post(
            "/api/v1/agents/strategy/invoke?async=true",
            json={"hypothesis": _valid_hypothesis_dict()},
            headers={"X-API-KEY": TEST_API_KEY},
        )

    assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.data}"
    body = json.loads(resp.data)
    assert "task_id" in body, f"Expected task_id in response, got: {body}"
    assert body["task_id"], "task_id must be non-empty"

    # run_strategy must NOT have been called — async path returns before invoking agent
    run_strategy_mock.assert_not_called()
