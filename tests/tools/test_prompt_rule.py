"""Phase 47.2-07 — Coordinator tool-discipline rule static check.

Target file: agents/agent0/prompts/agent.system.main.chat_evaluator.md
Plan 07 graduates the Plan 01 xfail stub: the Coordinator system prompt
includes the locked rule verbatim:

  "Use tools ONLY when additional data is required to make a decision"
  "Prefer minimal sufficient context"
"""
from __future__ import annotations

from pathlib import Path

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
_PROMPT_REL = "agents/agent0/prompts/agent.system.main.chat_evaluator.md"
_RULE_PRIMARY = "Use tools ONLY when additional data is required to make a decision"
_RULE_SECONDARY = "Prefer minimal sufficient context"


def test_coordinator_prompt_has_tool_rule():
    """Coordinator system prompt contains the locked tool-discipline rule verbatim."""
    prompt_path = _VM107_ROOT / _PROMPT_REL
    assert prompt_path.exists(), f"chat_evaluator prompt missing at {prompt_path}"

    content = prompt_path.read_text(encoding="utf-8")
    assert _RULE_PRIMARY in content, (
        f"Locked rule '{_RULE_PRIMARY}' not found in {_PROMPT_REL}"
    )
    assert _RULE_SECONDARY in content, (
        f"Locked rule '{_RULE_SECONDARY}' not found in {_PROMPT_REL}"
    )
