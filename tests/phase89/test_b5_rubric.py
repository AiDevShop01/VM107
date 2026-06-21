"""Phase 89 Plan 01 — B5 rubric golden-set regression tests.

Tests 1–8 from the plan's <behavior> block, covering:
  - Test 1: accept case (score ≥ 0.75)
  - Test 2: refine case (0.40 ≤ score < 0.75)
  - Test 3: second-fail degrades
  - Test 4: reject case (score < 0.40)
  - Test 5: B1 wiring (confidence_self_report set before reasoning_stream_end)
  - Test 6: word cap — >400 words → confidence_calibrated_and_concise forced to 0.0
  - Test 7: range scope — answer outside {start_ts, end_ts} → claims_within_cited_evidence forced to 0.0
  - Test 8: utility model routing — scorer uses Phase 43.1 utility-model alias (not chat model)

All tests use canned (mocked) utility-model scores — no real model calls.
Golden cases loaded from fixtures/b5_rubric_golden.yaml.

Per project lock: env-driven config, no hardcoded URLs, no fallback defaults.
"""
from __future__ import annotations

import pathlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"

# ---------------------------------------------------------------------------
# Helper: load the golden fixture
# ---------------------------------------------------------------------------


def _load_golden() -> dict:
    return yaml.safe_load((FIXTURES_DIR / "b5_rubric_golden.yaml").read_text())


# ---------------------------------------------------------------------------
# Helper: build a fake Agent mock
# ---------------------------------------------------------------------------


def _make_agent(
    profile: dict | None = None,
    response_text: str = "test response",
    b5_refinement_loops: int = 0,
    b5_cost_spent: float = 0.0,
) -> MagicMock:
    """Create a MagicMock mimicking the VM107 Agent interface for B5 tests."""
    agent = MagicMock()
    agent.profile = profile or {
        "id": "vm107.macro_investigator",
        "b5_self_eval": True,
        "b5_rubric_id": "rubric.macro_investigator_qa",
        "cost_budget_per_invocation": {
            "chat_model_usd": 0.50,
            "utility_model_usd": 0.20,
        },
    }
    agent.last_response = response_text

    # per-run data store
    _data: dict[str, Any] = {
        "b5_refinement_loops": b5_refinement_loops,
        "b5_utility_model_spend": b5_cost_spent,
        "prompt_context": None,
    }

    def _get(key: str, default: Any = None) -> Any:
        return _data.get(key, default)

    def _set(key: str, value: Any) -> None:
        _data[key] = value

    agent.get_data.side_effect = _get
    agent.set_data.side_effect = _set

    # Expose _data for assertions
    agent._data = _data
    return agent


# ---------------------------------------------------------------------------
# Helper: canned rubric dict matching rubric.macro_investigator_qa.yaml
# ---------------------------------------------------------------------------


def _canned_rubric() -> dict:
    return {
        "id": "rubric.macro_investigator_qa",
        "checks": [
            {"id": "cites_evidence", "weight": 0.30, "description": "Cites evidence"},
            {"id": "claims_within_cited_evidence", "weight": 0.25, "description": "Claims within cited"},
            {"id": "acknowledges_uncertainty", "weight": 0.20, "description": "Acknowledges uncertainty"},
            {"id": "correlation_not_causation", "weight": 0.15, "description": "Correlation not causation"},
            {"id": "confidence_calibrated_and_concise", "weight": 0.10, "description": "Calibrated and concise"},
        ],
        "threshold": {"accept": 0.75, "refine_below": 0.75, "reject_below": 0.40},
        "refinement": {"max_loops": 1, "on_second_fail": "degrade_to_uncertain"},
        "graceful_degradation_text": (
            "I'm not sure I can answer this confidently — the evidence I found\n"
            "was thin. You might try a narrower question (e.g. specific time\n"
            "window, specific asset pair).\n"
        ),
        "utility_model_routing": {"use_phase_43_1": True},
        "word_cap": {"target": 250, "hard_cap": 400},
    }


# ---------------------------------------------------------------------------
# Test 1: Accept case — score ≥ 0.75 → recommendation "accept"
# ---------------------------------------------------------------------------


@pytest.mark.phase89
@pytest.mark.quick
def test_rubric_scorer_accept_case():
    """Test 1: Golden answer scoring 0.85 → accept recommendation."""
    golden = _load_golden()
    accept_case = next(
        c for c in golden["investigator_cases"] if c["case_id"] == "INV-PASS-01"
    )
    answer_text = accept_case["answer_text"]
    rubric = _canned_rubric()

    # Mock utility-model to return per-check scores matching the golden case
    # (cites_evidence=0.90, claims_within=0.90, acknowledges=0.80, correlation=0.85, calibrated=1.0)
    canned_scores = {
        "cites_evidence": 0.90,
        "claims_within_cited_evidence": 0.90,
        "acknowledges_uncertainty": 0.80,
        "correlation_not_causation": 0.85,
        "confidence_calibrated_and_concise": 1.00,
    }

    with patch(
        "core.b5.rubric_scorer._call_utility_model_for_check",
        side_effect=lambda check_id, **_kw: canned_scores[check_id],
    ):
        from core.b5.rubric_scorer import score_answer

        result = score_answer(
            answer=answer_text,
            rubric=rubric,
            prompt_context={},
        )

    assert result["recommendation"] == "accept", (
        f"Expected accept, got {result['recommendation']!r} (total={result['total']:.3f})"
    )
    assert result["total"] >= 0.75
    assert "per_check" in result
    assert result["refinement_context"] is None


# ---------------------------------------------------------------------------
# Test 2: Refine case — 0.40 ≤ score < 0.75 → recommendation "refine"
# ---------------------------------------------------------------------------


@pytest.mark.phase89
@pytest.mark.quick
def test_rubric_scorer_refine_case():
    """Test 2: Answer scoring 0.60 → refine recommendation with context."""
    golden = _load_golden()
    refine_case = next(
        c for c in golden["investigator_cases"] if c["case_id"] == "INV-REFINE-01"
    )
    answer_text = refine_case["answer_text"]
    rubric = _canned_rubric()

    canned_scores = {
        "cites_evidence": 0.20,
        "claims_within_cited_evidence": 0.70,
        "acknowledges_uncertainty": 0.50,
        "correlation_not_causation": 0.50,
        "confidence_calibrated_and_concise": 1.00,
    }

    with patch(
        "core.b5.rubric_scorer._call_utility_model_for_check",
        side_effect=lambda check_id, **_kw: canned_scores[check_id],
    ):
        from core.b5.rubric_scorer import score_answer

        result = score_answer(
            answer=answer_text,
            rubric=rubric,
            prompt_context={},
        )

    assert result["recommendation"] == "refine", (
        f"Expected refine, got {result['recommendation']!r} (total={result['total']:.3f})"
    )
    assert 0.40 <= result["total"] < 0.75
    # Extension hook should build refinement context pointing to failing checks
    assert result["refinement_context"] is not None
    assert len(result["refinement_context"]) > 0


# ---------------------------------------------------------------------------
# Test 3: Second-fail degrades — extension replaces response on 2nd fail
# ---------------------------------------------------------------------------


@pytest.mark.phase89
@pytest.mark.quick
def test_b5_hook_second_fail_degrades():
    """Test 3: If refined response also scores < 0.75, extension degrades response."""
    rubric = _canned_rubric()

    # Agent that has already done 1 refinement loop
    agent = _make_agent(b5_refinement_loops=1, response_text="Still vague answer with no citations")

    canned_scores = {
        "cites_evidence": 0.20,
        "claims_within_cited_evidence": 0.50,
        "acknowledges_uncertainty": 0.40,
        "correlation_not_causation": 0.50,
        "confidence_calibrated_and_concise": 1.00,
    }

    with (
        patch("core.b5.rubric_scorer._call_utility_model_for_check",
              side_effect=lambda check_id, **_kw: canned_scores[check_id]),
        patch("core.b5.rubric_loader.load_rubric", return_value=rubric),
    ):
        import importlib
        import core.b5.response_self_check_hook as hook_module
        importlib.reload(hook_module)

        hook_module.run_b5_hook(agent)

    # After 2nd fail: response replaced with degradation text
    assert agent._data.get("b5_degraded") is True, "b5_degraded must be True on second fail"
    assert agent.last_response == rubric["graceful_degradation_text"], (
        "Response must be replaced with graceful_degradation_text on second fail"
    )
    # confidence_self_report still set (records the failing score)
    assert agent._data.get("confidence_self_report") is not None


# ---------------------------------------------------------------------------
# Test 4: Reject case — score < 0.40 → immediate degradation, no refinement
# ---------------------------------------------------------------------------


@pytest.mark.phase89
@pytest.mark.quick
def test_b5_hook_reject_degrades_immediately():
    """Test 4: 0.30 score → degradation without refinement attempt."""
    rubric = _canned_rubric()
    golden = _load_golden()
    reject_case = next(
        c for c in golden["investigator_cases"] if c["case_id"] == "INV-REJECT-01"
    )

    agent = _make_agent(response_text=reject_case["answer_text"])

    canned_scores = {
        "cites_evidence": 0.05,
        "claims_within_cited_evidence": 0.20,
        "acknowledges_uncertainty": 0.10,
        "correlation_not_causation": 0.10,
        "confidence_calibrated_and_concise": 0.00,  # word cap exceeded
    }

    with (
        patch("core.b5.rubric_scorer._call_utility_model_for_check",
              side_effect=lambda check_id, **_kw: canned_scores[check_id]),
        patch("core.b5.rubric_loader.load_rubric", return_value=rubric),
    ):
        import importlib
        import core.b5.response_self_check_hook as hook_module
        importlib.reload(hook_module)

        hook_module.run_b5_hook(agent)

    assert agent._data.get("b5_degraded") is True
    assert agent.last_response == rubric["graceful_degradation_text"]
    # No refinement loops attempted on reject
    assert agent._data.get("b5_refinement_loops", 0) == 0, (
        "Reject should not increment b5_refinement_loops"
    )


# ---------------------------------------------------------------------------
# Test 5: B1 wiring — confidence_self_report set before reasoning_stream_end
# ---------------------------------------------------------------------------


@pytest.mark.phase89
@pytest.mark.quick
def test_b5_hook_sets_confidence_self_report():
    """Test 5: set_data('confidence_self_report', score) is called by B5 hook."""
    rubric = _canned_rubric()

    agent = _make_agent(response_text="Gold rose [ref:release:CPI-2026-06-10]. Correlation only.")

    canned_scores = {
        "cites_evidence": 0.90,
        "claims_within_cited_evidence": 0.85,
        "acknowledges_uncertainty": 0.75,
        "correlation_not_causation": 0.80,
        "confidence_calibrated_and_concise": 1.00,
    }

    with (
        patch("core.b5.rubric_scorer._call_utility_model_for_check",
              side_effect=lambda check_id, **_kw: canned_scores[check_id]),
        patch("core.b5.rubric_loader.load_rubric", return_value=rubric),
    ):
        import importlib
        import core.b5.response_self_check_hook as hook_module
        importlib.reload(hook_module)

        hook_module.run_b5_hook(agent)

    # B5 hook must write confidence_self_report (Pitfall 8)
    assert "confidence_self_report" in agent._data, (
        "confidence_self_report must be set by B5 hook (Pitfall 8)"
    )
    assert isinstance(agent._data["confidence_self_report"], float)
    assert agent._data["confidence_self_report"] >= 0.75, (
        "accept case should have high confidence_self_report"
    )
    # b5_result also stored
    assert "b5_result" in agent._data


# ---------------------------------------------------------------------------
# Test 6: Word cap — >400 words forces confidence_calibrated_and_concise to 0.0
# ---------------------------------------------------------------------------


@pytest.mark.phase89
@pytest.mark.quick
def test_rubric_scorer_word_cap_forces_zero():
    """Test 6: Answer with word_count=420 forces confidence_calibrated_and_concise=0.0.

    The golden fixture's reject case may have fewer than 420 actual words
    (fixture expected_word_count is approximate). We construct a >400 word
    answer inline to guarantee the hard-cap trigger.
    """
    rubric = _canned_rubric()

    # Construct an answer that is definitively >400 words (Decision 9 hard cap = 400)
    # This simulates the class of answer the rubric rejects for verbosity.
    base_sentence = (
        "Gold is a safe haven asset that rises when there is uncertainty in the market. "
    )
    # Repeat enough times to exceed 400 words (15 words per sentence × 30 = 450 words)
    long_answer = " ".join([base_sentence.strip()] * 30)
    word_count = len(long_answer.split())
    assert word_count > 400, f"Test setup error: expected >400 words, got {word_count}"

    # Mock utility model to return 1.0 for confidence_calibrated_and_concise
    # (scorer must override it to 0.0 due to word cap)
    canned_scores = {
        "cites_evidence": 0.80,
        "claims_within_cited_evidence": 0.80,
        "acknowledges_uncertainty": 0.80,
        "correlation_not_causation": 0.80,
        "confidence_calibrated_and_concise": 1.00,  # LLM would give this, but scorer overrides
    }

    with patch(
        "core.b5.rubric_scorer._call_utility_model_for_check",
        side_effect=lambda check_id, **_kw: canned_scores[check_id],
    ):
        from core.b5 import score_answer

        result = score_answer(
            answer=long_answer,
            rubric=rubric,
            prompt_context={},
        )

    assert result["per_check"]["confidence_calibrated_and_concise"] == 0.0, (
        "Word count >400 must force confidence_calibrated_and_concise to 0.0 (Decision 9 hard cap)"
    )


# ---------------------------------------------------------------------------
# Test 7: Range scope — answer outside {start_ts, end_ts} → claims_within forced to 0.0
# ---------------------------------------------------------------------------


@pytest.mark.phase89
@pytest.mark.quick
def test_rubric_scorer_range_scope_forces_zero():
    """Test 7: Answer mentioning dates outside {start_ts, end_ts} → claims_within=0.0."""
    rubric = _canned_rubric()
    golden = _load_golden()
    oor_case = golden["out_of_range_case"]
    answer_text = oor_case["answer_text"]
    # Prompt is scoped to 2023; answer references 2008-2009 and 1970s
    prompt_context = {
        "zoom_range": {
            "start_ts": oor_case["prompt_start_ts"],
            "end_ts": oor_case["prompt_end_ts"],
        }
    }

    # LLM would give 0.80 for claims_within but scorer must override to 0.0
    canned_scores = {
        "cites_evidence": 0.50,
        "claims_within_cited_evidence": 0.80,
        "acknowledges_uncertainty": 0.50,
        "correlation_not_causation": 0.60,
        "confidence_calibrated_and_concise": 1.00,
    }

    with patch(
        "core.b5.rubric_scorer._call_utility_model_for_check",
        side_effect=lambda check_id, **_kw: canned_scores[check_id],
    ):
        from core.b5 import score_answer

        result = score_answer(
            answer=answer_text,
            rubric=rubric,
            prompt_context=prompt_context,
        )

    assert result["per_check"]["claims_within_cited_evidence"] == 0.0, (
        "Answer referencing dates outside {start_ts, end_ts} must force claims_within=0.0 (Decision 5)"
    )


# ---------------------------------------------------------------------------
# Test 8: Utility model routing — scorer uses Phase 43.1 utility alias
# ---------------------------------------------------------------------------


@pytest.mark.phase89
@pytest.mark.quick
def test_rubric_scorer_uses_utility_model_not_chat():
    """Test 8: Scorer calls _call_utility_model_for_check (not chat model)."""
    rubric = _canned_rubric()
    answer_text = "Gold rose because [ref:release:CPI-2026]. Real rates negative."

    call_log: list[str] = []

    def _mock_util_call(check_id: str, **_kw) -> float:
        call_log.append(("utility_model", check_id))
        return 0.85

    with patch(
        "core.b5.rubric_scorer._call_utility_model_for_check",
        side_effect=_mock_util_call,
    ):
        from core.b5.rubric_scorer import score_answer

        result = score_answer(
            answer=answer_text,
            rubric=rubric,
            prompt_context={},
        )

    # All 5 checks must have gone through the utility-model path
    utility_calls = [entry for entry in call_log if entry[0] == "utility_model"]
    assert len(utility_calls) == 5, (
        f"Expected 5 utility-model calls (one per check), got {len(utility_calls)}"
    )
    # No chat-model calls (we didn't patch chat model; if it were called it would raise)
    check_ids_called = {entry[1] for entry in utility_calls}
    expected_check_ids = {
        "cites_evidence",
        "claims_within_cited_evidence",
        "acknowledges_uncertainty",
        "correlation_not_causation",
        "confidence_calibrated_and_concise",
    }
    assert check_ids_called == expected_check_ids, (
        f"Utility model must be called for each check ID: {check_ids_called}"
    )
