"""Phase 89.2 Wave 0 — discovery endpoint scaffolding tests (REQ-89.2-2, REQ-89.2-3).

These tests target two Phase 89.2 endpoint surfaces:

  REQ-89.2-2: Per-agent invoke endpoint
    api.v1.agents.macro_relationship_discovery.invoke.MacroRelationshipDiscoveryInvoke
    landed by Phase 89.2 Plan 04.

  REQ-89.2-3: Generic dispatch endpoint
    api.v1.agents.run.AgentsRun routing to vm107.macro_relationship_discovery
    landed by Phase 89.2 Plan 05.

All 4 tests are xfail stubs at Wave 0 — they exist only so Plan 04 / Plan 05
tasks have real test targets to point their `<automated>` verify commands at
(Nyquist compliance). The import is wrapped in try/except ImportError so
`pytest --co` (collect-only) remains green pre-Plan-04/05.

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

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.phase89


@pytest.mark.xfail(
    reason="Phase 89.2 Plan 04 — per-agent invoke endpoint not yet implemented",
    strict=False,
)
def test_per_agent_invoke_200():
    """MacroRelationshipDiscoveryInvoke exists with the documented security pattern.

    Real handler exercise (200 status + envelope shape assertions) lands once
    Plan 04 produces the endpoint module. At Wave 0 we only assert the class
    surface contract: existence + 3 security classmethods returning the
    documented values (API key only, no session/CSRF — cross-VM call pattern).
    """
    try:
        from api.v1.agents.macro_relationship_discovery.invoke import (
            MacroRelationshipDiscoveryInvoke,
        )
    except ImportError:
        pytest.xfail(
            "api.v1.agents.macro_relationship_discovery.invoke not yet implemented"
        )
        return

    assert MacroRelationshipDiscoveryInvoke is not None
    assert MacroRelationshipDiscoveryInvoke.requires_api_key() is True
    assert MacroRelationshipDiscoveryInvoke.requires_auth() is False
    assert MacroRelationshipDiscoveryInvoke.requires_csrf() is False


@pytest.mark.xfail(
    reason="Phase 89.2 Plan 04 — per-agent invoke 422 path not yet implemented",
    strict=False,
)
def test_per_agent_invoke_422_on_bad_payload():
    """MacroRelationshipDiscoveryInvoke returns 422 when payload missing/malformed.

    Plan 04 wires Pydantic validation; at Wave 0 we just assert the class
    surface is reachable. Real 422 assertions land once the handler exists.
    """
    try:
        from api.v1.agents.macro_relationship_discovery.invoke import (
            MacroRelationshipDiscoveryInvoke,
        )
    except ImportError:
        pytest.xfail(
            "api.v1.agents.macro_relationship_discovery.invoke not yet implemented"
        )
        return

    # Plan 04 fills these in with a request fixture + .post() call asserting
    # 422 on both (a) missing both `message` and `run_mode` and (b) malformed
    # JSON body. At Wave 0 we just confirm the class is callable.
    assert callable(MacroRelationshipDiscoveryInvoke)


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
