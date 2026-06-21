"""Phase 89 Wave 0 smoke test.

Proves the user-driven agent runtime path (Phase 36 AgentRunner → Phase 43
router → Phase 70.5 ToolResultEnvelope → B1 artifact) is wired end-to-end
in the dev environment.

Pitfall 8 from 89-RESEARCH.md: the smoke test explicitly asserts
`confidence_self_report` is NULL-able in the B1 artifact — Wave 1's B5 hook
fills that slot; this test just confirms the slot exists.

Per project lock: env-driven config, no hardcoded URLs, no fallback defaults.
"""
from __future__ import annotations

import pytest


@pytest.mark.phase89
@pytest.mark.quick
def test_user_driven_runtime_smoke_path(
    agent_runner_harness,
    envelope_helpers,
):
    """End-to-end smoke: Phase 36 spawn → Phase 43 router → Phase 70.5 envelope → B1 artifact.

    The harness mocks all external tool calls so this test always runs even
    when the VM107 stack is offline. It does NOT skip in CI.
    """
    # Arrange: synthetic free-form prompt matching Phase 89 investigation queries
    prompt = "Why did Gold rise despite the CPI beat?"
    profile_id = "vm107.macro_investigator"

    # Act: spawn through harness
    result = agent_runner_harness(profile_id=profile_id, message=prompt)

    # Assert (a): Phase 43 router was invoked — harness records the call
    assert result["router_called"] is True, (
        "Phase 43 router must be invoked for all free-form prompts"
    )

    # Assert (b): Phase 70.5 ToolResultEnvelope was emitted on every mocked tool call
    envelopes = result["envelopes_emitted"]
    assert len(envelopes) >= 1, (
        "At least one ToolResultEnvelope must be emitted by the harness path"
    )
    for env in envelopes:
        assert "tool_name" in env, "Envelope missing tool_name"
        assert "confidence" in env, "Envelope missing confidence"
        assert "status" in env, "Envelope missing status"
        assert env["status"] in ("ok", "error", "degraded"), (
            f"Envelope status must be one of ok/error/degraded, got {env['status']!r}"
        )

    # Assert (c): B1 reasoning artifact write was scheduled with the expected shape
    artifact = result["b1_artifact"]
    assert artifact is not None, "B1 reasoning artifact must be written"
    assert artifact["profile_id"] == profile_id, (
        f"B1 artifact profile_id must match, expected {profile_id!r}"
    )

    # Pitfall 8 (89-RESEARCH.md): confidence_self_report slot must exist and be None now
    # Wave 1's B5 hook fills this; the smoke test just confirms the contract slot exists.
    assert "confidence_self_report" in artifact, (
        "B1 artifact contract must include confidence_self_report slot (Wave 1 fills it)"
    )
    assert artifact["confidence_self_report"] is None, (
        "confidence_self_report must be None at Wave 0 — Wave 1 B5 hook populates it"
    )


@pytest.mark.phase89
@pytest.mark.quick
def test_envelope_helpers_make_envelope(envelope_helpers):
    """Fixture envelope_helpers produces Phase 70.5-compliant dicts."""
    env = envelope_helpers.make_envelope(tool_name="macro_lookup", confidence=0.8)
    assert env["tool_name"] == "macro_lookup"
    assert env["confidence"] == 0.8
    assert "status" in env
    assert "timestamp" in env


@pytest.mark.phase89
@pytest.mark.quick
def test_belief_store_double_interface(belief_store_double):
    """Fixture belief_store_double exposes propose + query + active_blocking."""
    bs = belief_store_double()

    # propose records the call without hitting Postgres
    proposal_id = bs.propose(
        proposer_id="phase89.smoke",
        subject_type="indicator",
        subject_id="CPIAUCSL",
        confirms_belief=True,
        evidence={"source": "test"},
    )
    assert proposal_id is not None

    # query returns a canned result
    result = bs.query(subject_type="indicator", subject_id="CPIAUCSL")
    assert result is not None

    # active_blocking returns a list
    blocking = bs.active_blocking(indicator_id="CPIAUCSL")
    assert isinstance(blocking, list)

    # All calls are recorded
    assert len(bs._calls) >= 3


@pytest.mark.phase89
@pytest.mark.quick
def test_neo4j_macro_graph_double_interface(neo4j_macro_graph_double):
    """Fixture neo4j_macro_graph_double exposes walk + propose_edge."""
    graph = neo4j_macro_graph_double()

    analogues = graph.walk("CPIAUCSL")
    assert isinstance(analogues, list)

    graph.propose_edge(
        from_node="CPIAUCSL",
        to_node="DXY",
        edge_type="AFFECTS",
        strength=-0.6,
        confidence=0.8,
    )
    assert len(graph._edge_writes) == 1


@pytest.mark.phase89
@pytest.mark.quick
def test_phase90_forecast_stub(phase90_forecast_stub):
    """Fixture phase90_forecast_stub returns the Wave 2 fallback structure."""
    stub = phase90_forecast_stub()
    assert stub["status"] == "unavailable"
    assert "expected_dxy" in stub

    # set_unavailable toggle
    stub2 = phase90_forecast_stub(available=False)
    assert stub2["status"] == "unavailable"


@pytest.mark.phase89
@pytest.mark.quick
def test_phase91_alert_envelope_helper(phase91_alert_envelope_helper):
    """Fixture phase91_alert_envelope_helper builds jsonschema-valid envelopes."""
    helper = phase91_alert_envelope_helper()
    env = helper.make_alert(
        alert_type="macro_indicator",
        producer_agent_id="phase89.macro_investigator",
        subject_type="indicator",
        subject_id="CPIAUCSL",
        severity="Watch",
        b13_internal_severity="warning",
        confidence=0.72,
        explanation="CPI surprised upside vs consensus",
        citations=[],
    )
    assert env["event_type"] == "alert_candidate_created"
    assert env["severity"] == "Watch"
    assert env["schema_version"] == "0.1-provisional"
