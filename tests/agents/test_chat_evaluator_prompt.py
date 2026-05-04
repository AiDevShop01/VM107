"""
Wave 0 test scaffolding for chat evaluator prompt (no-delegation).

Tests in this file are xfail stubs. Downstream plan 47-03 removes the
xfail marker when it creates the agent.system.main.chat_evaluator.md
prompt file for the trade-evaluator role.
"""
import pytest


@pytest.mark.xfail(reason="Wave 0 stub — implementation in 47-03")
def test_no_delegation():
    """The chat_evaluator prompt file does NOT instruct the model to use call_subordinate. It is a separate file from agent.system.main.specifics.md (which is the thin-orchestrator routing prompt)."""
    from pathlib import Path
    p = Path("agents/agent0/prompts/agent.system.main.chat_evaluator.md")
    assert p.exists()
    text = p.read_text()
    assert "call_subordinate" not in text.lower()
    assert "trade" in text.lower() and "evaluat" in text.lower()
