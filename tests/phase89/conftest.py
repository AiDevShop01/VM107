"""Phase 89 shared fixtures — consumed by Waves 1-6 integration tests.

Per project locks:
  - NO `os.getenv("X", "default")` patterns — env-driven config, fail-fast.
  - All cross-VM URLs come from env vars; tests use in-memory doubles, never
    real Postgres/Mongo/Neo4j unless explicitly opted in via testcontainers.
  - Agent calls are always mocked through the harness — no live VM stack needed.

Fixtures exposed (6):
  - agent_runner_harness       — Phase 36 AgentRunner spawn path, all tools mocked.
                                  Returns {router_called, envelopes_emitted, b1_artifact}.
  - envelope_helpers           — Factory for Phase 70.5 ToolResultEnvelope dicts.
  - belief_store_double        — In-memory BeliefStore double: propose/query/active_blocking.
  - neo4j_macro_graph_double   — In-memory Neo4j walker double: walk/propose_edge.
  - phase90_forecast_stub      — Reads forecast_market_impact_stub.json; supports
                                  available/unavailable mode toggle for Wave 2 tests.
  - phase91_alert_envelope_helper — Builds + validates alert_candidate_created envelopes
                                    against the Phase 89 provisional JSON Schema.
"""
from __future__ import annotations

import json
import pathlib
import uuid
from datetime import datetime, timezone
from typing import Any

import jsonschema
import pytest

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"

# ─── Phase 70.5 ToolResultEnvelope contract ───────────────────────────────────
# Valid statuses per Phase 70.5 contract
_ENVELOPE_STATUSES = frozenset({"ok", "error", "degraded"})


class _EnvelopeHelpers:
    """Factory for Phase 70.5 ToolResultEnvelope test instances."""

    def make_envelope(
        self,
        tool_name: str,
        confidence: float = 0.5,
        status: str = "ok",
        result: Any = None,
        error_message: str | None = None,
        **extra: Any,
    ) -> dict:
        """Build a ToolResultEnvelope dict matching Phase 70.5 contract.

        Required fields: tool_name, confidence, status, timestamp.
        Optional: result, error_message, trace_id.
        """
        if status not in _ENVELOPE_STATUSES:
            raise ValueError(
                f"Envelope status must be one of {_ENVELOPE_STATUSES}, got {status!r}"
            )
        env = {
            "tool_name": tool_name,
            "confidence": confidence,
            "status": status,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "trace_id": str(uuid.uuid4()),
        }
        if result is not None:
            env["result"] = result
        if error_message is not None:
            env["error_message"] = error_message
        env.update(extra)
        return env

    def make_error_envelope(self, tool_name: str, error_message: str) -> dict:
        return self.make_envelope(
            tool_name=tool_name,
            confidence=0.0,
            status="error",
            error_message=error_message,
        )

    def make_degraded_envelope(self, tool_name: str, confidence: float = 0.3) -> dict:
        return self.make_envelope(
            tool_name=tool_name,
            confidence=confidence,
            status="degraded",
        )


# ─── In-memory BeliefStore double ─────────────────────────────────────────────

class _BeliefStoreDouble:
    """In-memory stand-in for VM107/core/belief/belief_store.py BeliefStore.

    Phase 89 agents touch three call sites:
      - propose(proposer_id, subject_type, subject_id, confirms_belief, evidence)
      - query(subject_type, subject_id)
      - active_blocking(indicator_id)

    All calls record into self._calls — never hit real Postgres.
    """

    def __init__(
        self,
        default_belief: dict | None = None,
        blocking_beliefs: list[dict] | None = None,
    ):
        self._default_belief = default_belief or {
            "belief_id": str(uuid.uuid4()),
            "probability": 0.5,
            "confidence": 0.5,
            "evidence_count": 1,
            "contradicting_count": 0,
            "lifecycle_state": "active",
            "is_active": True,
        }
        self._blocking_beliefs = blocking_beliefs or []
        self._calls: list[dict] = []

    def propose(
        self,
        *,
        proposer_id: str,
        subject_type: str,
        subject_id: str,
        confirms_belief: bool,
        evidence: dict,
    ) -> str:
        """Record call and return a synthetic belief_id."""
        proposal_id = str(uuid.uuid4())
        self._calls.append({
            "method": "propose",
            "proposer_id": proposer_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "confirms_belief": confirms_belief,
            "evidence": evidence,
            "result": proposal_id,
        })
        return proposal_id

    def query(self, *, subject_type: str, subject_id: str) -> dict | None:
        """Return canned belief or None."""
        self._calls.append({
            "method": "query",
            "subject_type": subject_type,
            "subject_id": subject_id,
        })
        return dict(self._default_belief)

    def active_blocking(self, *, indicator_id: str) -> list[dict]:
        """Return configured blocking beliefs — default empty (no blocks)."""
        self._calls.append({
            "method": "active_blocking",
            "indicator_id": indicator_id,
        })
        return list(self._blocking_beliefs)


# ─── In-memory Neo4j macro graph double ──────────────────────────────────────

class _Neo4jMacroGraphDouble:
    """In-memory stand-in for vm105.neo4j_macro_graph_walker.

    Phase 89 agents touch two call sites:
      - walk(indicator_id, max_hops=5) → list of analogue dicts
      - propose_edge(from_node, to_node, edge_type, strength, confidence)

    Configurable per-test via `set_walk_result(analogues)`.
    Writes are recorded in self._edge_writes for later assertion.
    """

    def __init__(self, walk_results: list[dict] | None = None):
        self._walk_results: list[dict] = walk_results or [
            {
                "source": "CPIAUCSL",
                "target": "DXY",
                "relationship_type": "AFFECTS",
                "strength": -0.62,
                "confidence": 0.78,
                "sample_size": 42,
                "evidence_period": "2010-01-01/2024-12-31",
                "hop_order": 0,
            }
        ]
        self._edge_writes: list[dict] = []
        self._walk_calls: list[dict] = []

    def walk(self, indicator_id: str, max_hops: int = 5) -> list[dict]:
        """Return configured analogue list without touching Neo4j."""
        self._walk_calls.append({"indicator_id": indicator_id, "max_hops": max_hops})
        return list(self._walk_results)

    # Alias used in some earlier wave tests
    def query_analogues(
        self,
        indicator: str,
        surprise_range: tuple[float, float] | None = None,
        k: int = 20,
    ) -> list[dict]:
        return self.walk(indicator)

    def propose_edge(
        self,
        *,
        from_node: str,
        to_node: str,
        edge_type: str,
        strength: float = 0.0,
        confidence: float = 0.0,
        **extra: Any,
    ) -> None:
        """Record the proposed edge — does not write to Neo4j."""
        self._edge_writes.append({
            "from_node": from_node,
            "to_node": to_node,
            "edge_type": edge_type,
            "strength": strength,
            "confidence": confidence,
            **extra,
        })

    def set_walk_result(self, analogues: list[dict]) -> None:
        """Override the default walk result for per-test customisation."""
        self._walk_results = analogues


# ─── Phase 90 forecast stub ───────────────────────────────────────────────────

class _Phase90ForecastStub:
    """Wraps forecast_market_impact_stub.json.

    Supports available/unavailable mode toggle for Wave 2 counterfactual tests.
    When `available=False` (default at Wave 0), returns the stub's unavailable path.
    When `available=True`, returns a synthetic "available" response — used in
    Wave 2 tests that exercise the wired Phase 90 Layer 4 path.
    """

    def __init__(self):
        stub_path = FIXTURES_DIR / "forecast_market_impact_stub.json"
        if not stub_path.exists():
            pytest.skip("forecast_market_impact_stub.json fixture not yet created")
        self._stub = json.loads(stub_path.read_text())

    def __call__(self, available: bool = False) -> dict:
        if not available:
            return dict(self._stub)
        # Synthetic "available" response — Wave 2 populates realistic values
        return {
            "status": "ok",
            "fallback_path": None,
            "expected_dxy": -0.4,
            "expected_gold": 1.2,
            "expected_spx": -0.6,
            "expected_ust10y": 0.08,
        }

    def set_unavailable(self) -> dict:
        """Convenience alias used in Wave 2 stub-path tests."""
        return self(available=False)


# ─── Phase 91 alert envelope helper ──────────────────────────────────────────

_ALERT_SEVERITIES = frozenset({"Info", "Watch", "Important", "Critical", "RegimeChange"})
_B13_SEVERITIES = frozenset({"info", "warning", "blocking"})
_ALERT_TYPES = frozenset({
    "regime", "correlation", "discovery", "contradiction",
    "macro_indicator", "liquidity", "price",
})


class _Phase91AlertEnvelopeHelper:
    """Builds + validates alert_candidate_created envelopes.

    Each `make_alert()` call validates the result against the provisional
    JSON Schema in `fixtures/alert_candidate_event.schema.json` before
    returning — this surfaces schema-drift bugs the moment they happen.
    """

    def __init__(self):
        schema_path = FIXTURES_DIR / "alert_candidate_event.schema.json"
        if not schema_path.exists():
            pytest.skip("alert_candidate_event.schema.json fixture not yet created")
        self._schema = json.loads(schema_path.read_text())
        self._validator = jsonschema.Draft7Validator(self._schema)

    def make_alert(
        self,
        *,
        alert_type: str,
        producer_agent_id: str,
        subject_type: str,
        subject_id: str,
        severity: str,
        b13_internal_severity: str,
        confidence: float,
        explanation: str,
        citations: list[str] | None = None,
        **extra: Any,
    ) -> dict:
        """Build and validate a Phase 91 alert_candidate_created envelope."""
        if severity not in _ALERT_SEVERITIES:
            raise ValueError(f"severity must be one of {_ALERT_SEVERITIES}")
        if b13_internal_severity not in _B13_SEVERITIES:
            raise ValueError(f"b13_internal_severity must be one of {_B13_SEVERITIES}")
        if alert_type not in _ALERT_TYPES:
            raise ValueError(f"alert_type must be one of {_ALERT_TYPES}")

        envelope = {
            "event_type": "alert_candidate_created",
            "alert_type": alert_type,
            "producer_agent_id": producer_agent_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "severity": severity,
            "b13_internal_severity": b13_internal_severity,
            "confidence": confidence,
            "explanation": explanation,
            "citations": citations if citations is not None else [],
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
            "schema_version": "0.1-provisional",
            **extra,
        }
        errors = list(self._validator.iter_errors(envelope))
        if errors:
            raise ValueError(
                f"Alert envelope failed schema validation: "
                + "; ".join(e.message for e in errors[:3])
            )
        return envelope


# ─── Agent runner harness ─────────────────────────────────────────────────────

class _AgentRunnerHarness:
    """Phase 36 AgentRunner harness — all external tool calls mocked.

    Accepts a profile_id + message and returns:
      {
        router_called: bool,
        envelopes_emitted: list[dict],  # Phase 70.5 envelopes
        b1_artifact: dict,              # B1 reasoning artifact written
        monologue_trace: list[str],
      }

    This harness deliberately does NOT import the real AgentRunner to avoid
    requiring the full VM107 Django stack in CI. It simulates the call graph
    at the interface level, recording which contracts were exercised.
    """

    def __init__(self, envelope_helpers: _EnvelopeHelpers):
        self._envelope_helpers = envelope_helpers
        self._calls: list[dict] = []

    def __call__(self, *, profile_id: str, message: str) -> dict:
        """Simulate Phase 36 → 43 → 70.5 → B1 path."""
        # Phase 43 router invocation (mocked)
        router_called = True
        self._calls.append({"step": "phase43_router", "profile_id": profile_id, "message": message})

        # Phase 70.5 ToolResultEnvelope emissions for each tool call in the path
        # Harness always emits one envelope for the macro_lookup tool as a representative trace
        envelopes: list[dict] = [
            self._envelope_helpers.make_envelope(
                tool_name="macro_lookup",
                confidence=0.75,
                status="ok",
                result={"indicator": "CPIAUCSL", "actual": 3.4, "forecast": 3.3},
            )
        ]

        # B1 artifact written — confidence_self_report is None at Wave 0 per Pitfall 8
        b1_artifact = {
            "artifact_id": str(uuid.uuid4()),
            "profile_id": profile_id,
            "prompt": message,
            "answer": "Gold rose despite the CPI beat because real rates remained negative...",
            "confidence_self_report": None,  # Wave 1 B5 hook fills this
            "tool_envelopes": envelopes,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        }

        return {
            "router_called": router_called,
            "envelopes_emitted": envelopes,
            "b1_artifact": b1_artifact,
            "monologue_trace": [
                "router: dispatched to macro_investigator",
                "tool: macro_lookup → ok",
                "artifact: B1 written",
            ],
        }


# ─── Pytest fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def envelope_helpers() -> _EnvelopeHelpers:
    """Phase 70.5 ToolResultEnvelope factory — session-scoped (stateless)."""
    return _EnvelopeHelpers()


@pytest.fixture
def agent_runner_harness(envelope_helpers: _EnvelopeHelpers):
    """Phase 36 AgentRunner harness with all external calls mocked.

    Returns a callable: harness(profile_id=..., message=...) → result dict.
    """
    return _AgentRunnerHarness(envelope_helpers=envelope_helpers)


@pytest.fixture
def belief_store_double():
    """Factory for in-memory BeliefStore doubles.

    Usage:
        bs = belief_store_double()                # default canned belief
        bs = belief_store_double(default_belief={...})  # custom canned belief
        bs = belief_store_double(blocking_beliefs=[...])  # configure active blocks
    """
    def _factory(
        default_belief: dict | None = None,
        blocking_beliefs: list[dict] | None = None,
    ) -> _BeliefStoreDouble:
        return _BeliefStoreDouble(
            default_belief=default_belief,
            blocking_beliefs=blocking_beliefs,
        )
    return _factory


@pytest.fixture
def neo4j_macro_graph_double():
    """Factory for in-memory Neo4j macro graph doubles.

    Usage:
        graph = neo4j_macro_graph_double()                  # default walk result
        graph = neo4j_macro_graph_double(walk_results=[...])  # custom analogues
    """
    def _factory(walk_results: list[dict] | None = None) -> _Neo4jMacroGraphDouble:
        return _Neo4jMacroGraphDouble(walk_results=walk_results)
    return _factory


@pytest.fixture(scope="session")
def phase90_forecast_stub() -> _Phase90ForecastStub:
    """Phase 90 Layer 4 stub — reads forecast_market_impact_stub.json.

    Session-scoped because fixture file is read-only. Wave 2 uses
    stub.set_unavailable() to test the counterfactual fallback path.
    """
    return _Phase90ForecastStub()


@pytest.fixture(scope="session")
def phase91_alert_envelope_helper() -> _Phase91AlertEnvelopeHelper:
    """Phase 91 alert envelope builder + JSON Schema validator.

    Session-scoped because the JSON Schema is read-only. Each make_alert()
    call validates the result against the provisional schema before returning.
    """
    return _Phase91AlertEnvelopeHelper
