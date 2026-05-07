"""Phase 47.2-01 Wave 0 — xfail static check for the Coordinator tool-discipline rule.

Target file: agents/agent0/prompts/agent.system.main.chat_evaluator.md
Plan 07 will graduate this xfail spec to GREEN by amending the Coordinator
system prompt to include the locked rule verbatim:

  "Use tools ONLY when additional data is required to make a decision"
"""
from __future__ import annotations

from pathlib import Path

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
_PROMPT_REL = "agents/agent0/prompts/agent.system.main.chat_evaluator.md"
_RULE = "Use tools ONLY when additional data is required to make a decision"


@pytest.mark.xfail(
    reason="Wave 0 stub — Plan 07 amends chat_evaluator prompt with tool-discipline rule",
    strict=False,
)
def test_coordinator_prompt_has_tool_rule():
    """Coordinator system prompt contains the locked tool-discipline rule verbatim."""
    prompt_path = _VM107_ROOT / _PROMPT_REL
    if not prompt_path.exists():
        pytest.fail(
            f"Wave 0 stub — Plan 07 ships {_PROMPT_REL} (file missing)"
        )
    content = prompt_path.read_text(encoding="utf-8")
    if _RULE not in content:
        pytest.fail(
            f"Wave 0 stub — Plan 07 inserts '{_RULE}' into {_PROMPT_REL}"
        )
