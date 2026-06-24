"""Phase 89.2 discovery endpoint tests (REQ-89.2-2, REQ-89.2-3).

These tests target two Phase 89.2 endpoint surfaces:

  REQ-89.2-2: Per-agent invoke endpoint  (Plan 89.2-04 — IMPLEMENTED)
    api.v1.agents.macro_relationship_discovery.invoke.MacroRelationshipDiscoveryInvoke

  REQ-89.2-3: Generic dispatch endpoint  (Plan 89.2-05 — still xfail)
    api.v1.agents.run.AgentsRun routing to vm107.macro_relationship_discovery

Per-agent invoke tests (test_per_agent_invoke_200 / _422_on_bad_payload) were
flipped from xfail to real assertions by Plan 04. Generic dispatch tests
remain xfail until Plan 05 lands.

Per project locks:
  - No live Postgres / Neo4j / VM102 — every agent dispatch is mocked via
    unittest.mock.patch.
  - No `pytest.importorskip` — we want xfail→xpass when the endpoint module
    lands, not a silent skip.
  - Endpoint security classmethods (requires_api_key / requires_auth /
    requires_csrf) follow the VM107 pattern: API key only (True/False/False)
    for cross-VM Dagster→VM107 calls.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.phase89


# ---------------------------------------------------------------------------
# REQ-89.2-2 — per-agent invoke endpoint (Plan 04)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_agent_invoke_200():
    """MacroRelationshipDiscoveryInvoke returns 200 + the agent's exact 3-key dict.

    Patches the agent class on the AGENT MODULE namespace so the late-import
    inside process() resolves to the mock. Verifies the handler:
      - Returns Flask Response with status_code=200.
      - JSON-encodes the agent's run() return dict verbatim (exact 3 keys).
      - Honours documented security classmethods (True / False / False).
    """
    from api.v1.agents.macro_relationship_discovery.invoke import (
        MacroRelationshipDiscoveryInvoke,
    )

    assert MacroRelationshipDiscoveryInvoke.requires_api_key() is True
    assert MacroRelationshipDiscoveryInvoke.requires_auth() is False
    assert MacroRelationshipDiscoveryInvoke.requires_csrf() is False

    fake_result = {
        "proposals_created": 3,
        "scan_duration_s": 1.5,
        "throughput_action": "ok",
    }

    # Patch on the agent module namespace — the handler does a late import
    # `from agents.macro_relationship_discovery.agent import MacroRelationshipDiscovery`
    # so the patch must target the source module, not the handler's import.
    with patch(
        "agents.macro_relationship_discovery.agent.MacroRelationshipDiscovery"
    ) as MockAgentCls:
        mock_instance = MagicMock()
        mock_instance.run.return_value = fake_result
        MockAgentCls.return_value = mock_instance

        handler = MacroRelationshipDiscoveryInvoke(app=None, thread_lock=None)
        fake_request = MagicMock()

        response = await handler.process(
            {"message": "smoke", "run_mode": "manual"},
            fake_request,
        )

    assert response.status_code == 200, response.get_data(as_text=True)
    body = json.loads(response.get_data(as_text=True))
    assert body == fake_result, (
        f"Handler must return the agent's run() dict verbatim; got {body}"
    )
    # Confirm the handler invoked the agent with the input kwargs.
    mock_instance.run.assert_called_once_with(message="smoke", run_mode="manual")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_payload",
    [
        pytest.param({"message": 123, "run_mode": "manual"}, id="int_message"),
        pytest.param({"message": "ok", "run_mode": ["foo"]}, id="list_run_mode"),
        pytest.param({"message": {"oops": True}, "run_mode": "manual"}, id="dict_message"),
    ],
)
async def test_per_agent_invoke_422_on_bad_payload(bad_payload):
    """MacroRelationshipDiscoveryInvoke returns 422 when message/run_mode is not a string.

    Type-validates the payload before invoking the agent (so the agent is
    never called on bad input). Verifies:
      - response.status_code == 422
      - JSON body has key "error"
      - The agent class is NOT instantiated (mock.assert_not_called).
    """
    from api.v1.agents.macro_relationship_discovery.invoke import (
        MacroRelationshipDiscoveryInvoke,
    )

    with patch(
        "agents.macro_relationship_discovery.agent.MacroRelationshipDiscovery"
    ) as MockAgentCls:
        handler = MacroRelationshipDiscoveryInvoke(app=None, thread_lock=None)
        fake_request = MagicMock()

        response = await handler.process(bad_payload, fake_request)

    assert response.status_code == 422, response.get_data(as_text=True)
    body = json.loads(response.get_data(as_text=True))
    assert "error" in body, f"422 body must include 'error' key; got {body}"
    # Agent must NOT be constructed/invoked on bad payload — validation
    # rejects before the late import resolves.
    MockAgentCls.assert_not_called()


@pytest.mark.xfail(
    reason="Phase 89.2 Plan 05 — generic /api/v1/agents/run dispatch not yet implemented",
    strict=False,
)
def test_generic_run_endpoint_routes():
    """AgentsRun dispatches profile_id=vm107.macro_relationship_discovery correctly.

    Asserts:
      - api.v1.agents.run.AgentsRun class exists
      - Same 3-method security contract (True / False / False)
      - Dispatch to vm107.macro_relationship_discovery calls
        MacroRelationshipDiscovery.run(...) (mocked)
    """
    try:
        from api.v1.agents.run import AgentsRun
    except ImportError:
        pytest.xfail("api.v1.agents.run.AgentsRun not yet implemented")
        return

    assert AgentsRun is not None
    assert AgentsRun.requires_api_key() is True
    assert AgentsRun.requires_auth() is False
    assert AgentsRun.requires_csrf() is False

    # Mock the agent module that AgentsRun must import and dispatch to.
    with patch(
        "agents.macro_relationship_discovery.agent.MacroRelationshipDiscovery"
    ) as MockAgent:
        instance = MagicMock()
        instance.run.return_value = {
            "proposals_created": 0,
            "scan_duration_s": 0.0,
            "throughput_action": "ok",
        }
        MockAgent.return_value = instance

        # Plan 05 wires the actual handler call — at Wave 0 we just confirm
        # the agent module is the dispatch target and the mock is exercised
        # once the production wiring is in place.
        # This assertion will become a real .post() call in Plan 05.
        assert MockAgent is not None


@pytest.mark.xfail(
    reason="Phase 89.2 Plan 05 — unknown-profile 404 path not yet implemented",
    strict=False,
)
def test_generic_run_unknown_profile_404():
    """AgentsRun returns 404 + JSON {"error": "Unknown agent profile: ..."} for unknown profile.

    Plan 05 implements the unknown-profile guard. Wave 0 stub confirms the
    class is reachable so Plan 05 can assert the 404 path without breaking
    Nyquist sampling.
    """
    try:
        from api.v1.agents.run import AgentsRun
    except ImportError:
        pytest.xfail("api.v1.agents.run.AgentsRun not yet implemented")
        return

    # Plan 05 fills this in with a request fixture + .post() call asserting
    # 404 status code and the exact error JSON body for an unrecognised
    # profile_id (e.g., "vm107.nonexistent_agent"). At Wave 0 we just
    # confirm the class surface is reachable.
    assert AgentsRun is not None
    assert hasattr(AgentsRun, "requires_api_key"), (
        "AgentsRun must expose the VM107 security classmethod contract"
    )
