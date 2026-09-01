"""Phase 155 AZE-07 — Subagent envelope + stop_reason branching + fail-loud dispatch.

Targets (built in 155-02/03):
  * ``contracts.economic_intelligence.subagent_contract`` — SubagentRequest / SubagentResult /
    StopReason (the net-new AZE-07 envelope).
  * ``agents.macro_ask_executor.executor.MacroAskExecutor`` — capability-checked dispatch that
    turns an unknown id into a loud ``stop_reason="error"`` result (never a silent skip) and
    degrades a non-``completed`` section without collapsing the whole answer.

RED by import until those land; each test names the exact contract/behaviour it will turn GREEN.
"""
from __future__ import annotations

import pytest

# RED-on-target: the AZE-07 envelope does not exist until 155-02.
from contracts.economic_intelligence.subagent_contract import (
    StopReason,
    SubagentRequest,
    SubagentResult,
)
from agents.macro_ask_executor.executor import MacroAskExecutor


def test_subagent_request_constructs_and_forbids_extra():
    req = SubagentRequest(
        prompt="Explain the inflation pillar move.",
        output_schema="SpecialistResponse",
        tool_filter={"allowed_tools": ["vm101.economic_event"], "denied_tools": []},
        persona="inflation_analyst",
        max_depth=1,
    )
    assert req.prompt
    with pytest.raises(Exception):  # extra="forbid"
        SubagentRequest(
            prompt="x",
            output_schema="SpecialistResponse",
            tool_filter={},
            persona="p",
            max_depth=1,
            unexpected_key="boom",
        )


def test_subagent_result_constructs_and_forbids_extra():
    res = SubagentResult(
        output="ok",
        structured={"answer": "…"},
        stop_reason="completed",
        diagnostic={},
    )
    assert res.stop_reason == "completed"
    with pytest.raises(Exception):  # extra="forbid"
        SubagentResult(
            output="ok",
            structured={},
            stop_reason="completed",
            diagnostic={},
            leaked="boom",
        )


def test_stop_reason_union_members_exact():
    """StopReason is exactly {completed, aborted, error, max_tokens, refusal} — no more, no less."""
    members = set(StopReason.__args__) if hasattr(StopReason, "__args__") else set(StopReason)
    assert members == {"completed", "aborted", "error", "max_tokens", "refusal"}


def test_unknown_id_fails_loud(stub_registry, stub_pillar_fetcher, fake_plan):
    """Dispatching an id absent from the registry → SubagentResult stop_reason='error' naming
    the id. It must NEVER be silently skipped (T-155-03 spoofing guard)."""
    executor = MacroAskExecutor(registry=stub_registry, pillar_fetcher=stub_pillar_fetcher())
    plan = fake_plan(required_agents=["vm107.does_not_exist"])
    result = executor.dispatch_one("vm107.does_not_exist", plan=plan)
    assert result.stop_reason == "error"
    assert "vm107.does_not_exist" in (result.output or "") + str(result.diagnostic)


def test_stop_reason_branching(stub_registry, stub_pillar_fetcher, fake_plan):
    """A non-`completed` sub-result degrades only its own section, not the whole answer."""
    fetcher = stub_pillar_fetcher(degraded="Liquidity")
    executor = MacroAskExecutor(registry=stub_registry, pillar_fetcher=fetcher)
    plan = fake_plan(
        required_agents=["vm107.inflation_analyst", "vm107.liquidity_analyst"]
    )
    composed = executor.run(query="inflation vs liquidity", plan=plan)
    # Inflation still answered; liquidity degraded is surfaced under limitations, answer non-empty.
    assert composed["answer"]
    assert any("liquidity" in lim.lower() for lim in composed["limitations"])


def test_tool_filter_populated_from_profile(stub_registry, stub_pillar_fetcher, fake_plan):
    """Dispatching a known specialist builds a SubagentRequest whose tool_filter carries that
    specialist's allowed_tools/denied_tools from registry/agent_profile/*.yaml — the scope is
    carried through the envelope for the Phase-157 enforcement upgrade even though the
    in-process path leaves _05_tool_scope_filter moot (SPEC AC#1 note)."""
    executor = MacroAskExecutor(registry=stub_registry, pillar_fetcher=stub_pillar_fetcher())
    req = executor.build_subagent_request("vm107.inflation_analyst", plan=fake_plan())
    assert isinstance(req, SubagentRequest)
    assert "allowed_tools" in req.tool_filter
    assert "denied_tools" in req.tool_filter
