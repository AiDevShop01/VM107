"""Phase 83 hard-dependency preflight test — confirms three upstream phases are live.

REQ: Wave 0 gate — all three tests MUST be GREEN before any Phase 83 wave begins.

Tests:
    test_phase_43_router_callable: Phase 43 ModelRouter is importable and can produce
        a RoutingDecision from a RouterContext (infrastructure deps mocked via MagicMock
        since the goal is to prove the module exists and runs, not to probe Redis/Mongo).
    test_phase_47_6_registry_loader_callable: Phase 47.6 CapabilityRegistry loader can
        load the real VM107 registry (the production registry root). Returned snapshot
        has required fields: id, status, version.
    test_phase_70_5_envelope_importable: fingpt_core.contracts.tool_envelope.ToolResultEnvelope[T]
        imports cleanly and can be instantiated with a Pydantic model payload.

If any test FAILS, halt Phase 83 and raise a blocker on the corresponding upstream phase.
Do NOT use xfail — failures here are blockers, not accepted flakiness.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
import pytest
from pathlib import Path
from unittest.mock import MagicMock


@pytest.mark.phase83
def test_phase_43_router_callable():
    """Phase 43 LLM router is callable with Agent Hands (utility) profile.

    Verifies that:
    - core.routing.router.ModelRouter is importable
    - core.routing.schemas.RouterContext / RoutingDecision are importable
    - A ModelRouter instance can produce a RoutingDecision from a RouterContext

    Infrastructure deps (Redis, Mongo, SignalAccumulator) are mocked because this
    test probes *existence and call-correctness*, not live infrastructure.
    The from_yaml factory is exercised via the real conf/model_routing.yaml so the
    YAML config itself is validated.
    """
    from core.routing.router import ModelRouter
    from core.routing.schemas import RouterContext, RoutingDecision
    from core.routing.affinity import AffinityMap
    from core.routing.budget_gate import BudgetGate
    from core.routing.alert_pipeline import AlertPipeline
    from core.routing.peak_schedule import PeakSchedule

    # Locate real routing config
    vm107_root = Path(__file__).resolve().parents[2]
    routing_yaml = vm107_root / "conf" / "model_routing.yaml"
    assert routing_yaml.exists(), (
        f"model_routing.yaml not found at {routing_yaml} — "
        "Phase 43 configuration file is missing."
    )

    # Build router with real affinity config + mocked infrastructure
    affinity = AffinityMap.from_yaml(str(routing_yaml))
    mock_redis = MagicMock()
    # Return empty dict on cache reads → triggers _warm_from_mongo path
    mock_redis.hgetall.return_value = {}
    mock_redis.hset.return_value = None
    mock_redis.expire.return_value = True
    mock_mongo = MagicMock()
    # Return None from Mongo goal lookup → BudgetGate returns (True, "unknown_goal") → routing proceeds
    mock_mongo.fingpt_agents.agent_goals.find_one.return_value = None
    mock_logger = MagicMock()
    mock_signal_acc = MagicMock()

    budget_gate = BudgetGate(mock_redis, mock_mongo, mock_logger, budget_caps=affinity.budget_caps)
    alert_pipeline = AlertPipeline(mock_mongo, mock_signal_acc, None, mock_logger)
    peak = PeakSchedule.from_yaml(affinity.raw["routing"])

    router = ModelRouter(affinity, budget_gate, alert_pipeline, peak, mock_mongo, mock_logger)

    # Build RouterContext with Agent Hands (utility) profile
    ctx = RouterContext(
        task_id="phase83-preflight",
        goal_id="vm107.preflight",
        agent_id="test",
        task_type="preflight",
        priority="P3",
        latency_sla_ms=30000,
        brain_context={"mode": "exploitation"},
        path="utility",
    )

    decision = router.decide(ctx)

    assert decision is not None, "ModelRouter.decide() returned None — Phase 43 routing broken"
    assert isinstance(decision, RoutingDecision), (
        f"Expected RoutingDecision, got {type(decision).__name__}"
    )
    assert decision.primary, "RoutingDecision.primary is empty — no model selected"


@pytest.mark.phase83
def test_phase_47_6_registry_loader_callable():
    """Phase 47.6 capability registry loader can read the live VM107 registry.

    Verifies that:
    - core.registry.loader.load_all_yamls is importable
    - It can traverse the real VM107/registry/ tree
    - The existing vm107.intelligence_feed.macro YAML is loaded correctly
    - The returned entry dict has 'id', 'status', 'version' keys (Phase 47.6 schema)
    """
    from core.registry.loader import load_all_yamls

    vm107_root = Path(__file__).resolve().parents[2]
    registry_root = vm107_root / "registry"

    assert registry_root.exists(), (
        f"VM107 registry root not found at {registry_root} — Phase 47.6 registry missing."
    )

    entries = load_all_yamls(registry_root)
    assert len(entries) > 0, "load_all_yamls returned empty list — registry has no YAMLs"

    # Find the macro intelligence feed entry (should already exist from Phase 65/66)
    macro_entries = [
        (path, data)
        for path, data in entries
        if "intelligence_feed.macro" in str(path)
    ]
    assert len(macro_entries) >= 1, (
        "vm107.intelligence_feed.macro YAML not found in registry — "
        "expected file: VM107/registry/tool/vm107.intelligence_feed.macro.yaml"
    )

    _, macro_data = macro_entries[0]
    missing_keys = [k for k in ("id", "status", "version") if k not in macro_data]
    assert not missing_keys, (
        f"vm107.intelligence_feed.macro YAML is missing required keys: {missing_keys}. "
        "Phase 47.6 schema requires id, status, version on every tool entry."
    )


@pytest.mark.phase83
def test_phase_70_5_envelope_importable():
    """Phase 70.5 ToolResultEnvelope[T] is importable and instantiatable.

    Verifies that:
    - fingpt_core.contracts.tool_envelope.ToolResultEnvelope is importable
    - ToolResultEnvelope[T] can be instantiated with a Pydantic model payload
    - The envelope has the expected schema_version constant
    """
    from fingpt_core.contracts.tool_envelope import ToolResultEnvelope, ENVELOPE_SCHEMA_VERSION
    from pydantic import BaseModel

    assert ENVELOPE_SCHEMA_VERSION == "1.0", (
        f"ENVELOPE_SCHEMA_VERSION is {ENVELOPE_SCHEMA_VERSION!r}, expected '1.0'. "
        "Schema version bump requires a phase decision — check Phase 70.5 CONTEXT.md."
    )

    # Define a minimal payload model for the generic parameter
    class _PrefightPayload(BaseModel):
        test_key: str
        value: int

    # Instantiate ToolResultEnvelope[_PreflightPayload] — confirms Generic[T] works
    # Provide all required fields per the Phase 70.5 schema
    envelope = ToolResultEnvelope[_PrefightPayload](
        envelope_id=uuid.uuid4(),
        tool_name="phase83.preflight",
        tool_version="1.0.0",
        outcome_class="success",
        success=True,
        confidence=0.99,
        generated_at=datetime.now(tz=timezone.utc),
        registry_snapshot_hash="phase83-preflight-noop-hash",
        payload_schema_version="1.0.0",
        payload=_PrefightPayload(test_key="phase83", value=83),
    )

    assert envelope is not None, "ToolResultEnvelope instantiation returned None"
    assert envelope.tool_name == "phase83.preflight"
    assert envelope.outcome_class == "success"
    assert envelope.payload.test_key == "phase83"
