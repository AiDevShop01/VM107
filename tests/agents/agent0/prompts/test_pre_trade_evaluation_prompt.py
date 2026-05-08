"""Phase 47.3 — pre_trade_evaluation.md prompt rewrite assertions.

The Mode B prompt is rewritten to constrain the LLM to narrative-only output:
reasoning_summary, risks, invalidations, next_action — and EXPLICITLY forbid
modifying score/recommendation/confidence/category_results (Python-owned).

Wave 0 — graduates in Plan 06 (prompt rewrite ships).
"""
from pathlib import Path

PROMPT_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "agents"
    / "agent0"
    / "prompts"
    / "agent.system.main.pre_trade_evaluation.md"
)


def test_prompt_instructs_narrative_only():
    """Prompt MUST instruct LLM to produce ONLY reasoning_summary, risks,
    invalidations, next_action."""
    text = PROMPT_PATH.read_text()
    assert "reasoning_summary" in text
    assert "risks" in text
    assert "invalidations" in text
    assert "next_action" in text


def test_prompt_forbids_modifying_python_owned_fields():
    """Prompt MUST explicitly forbid modifying score / recommendation /
    confidence / category_results."""
    text = PROMPT_PATH.read_text()
    # Look for the forbidden-fields language
    forbidden_signal = (
        ("do not modify" in text.lower() or "never modify" in text.lower() or
         "cannot modify" in text.lower())
        and "score" in text.lower()
        and "recommendation" in text.lower()
    )
    assert forbidden_signal, "Prompt must explicitly forbid modifying Python-owned fields"


def test_prompt_documents_framework_result_block():
    """Prompt MUST document the `## Framework Result` block in the user message."""
    text = PROMPT_PATH.read_text()
    assert "framework_result" in text.lower() or "framework result" in text.lower()


def test_prompt_partial_context_risk_requirement():
    """If partial_context: true, LLM MUST include capability-name risk."""
    text = PROMPT_PATH.read_text()
    assert "partial_context" in text


def test_prompt_hard_reject_acknowledgement_requirement():
    """If hard_reject_reasons non-empty, LLM next_action MUST acknowledge veto."""
    text = PROMPT_PATH.read_text()
    assert "hard_reject" in text.lower()
