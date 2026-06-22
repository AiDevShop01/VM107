"""Phase 89.1 Plan 02 — B5 dispatch-path integration test.

Exercises run_b5_hook end-to-end using:
  - The actual registry/agent_profile/vm107.macro_investigator.yaml (via YAML load,
    NOT CapabilityRegistry — we don't want a full registry boot in CI).
  - A production-shaped agent stub (_ProductionAgentStub from test_b5_hook_rca.py).
  - A realistic loop_data stub with params_temporary["current_agent_response"] set
    to an investigator-style answer with citation chips + json fence envelope.
  - load_rubric patched to return a canned rubric (avoids CapabilityRegistry boot).
  - _call_utility_model_for_check patched to return realistic per-check floats
    (avoids LLM cost in CI; we are testing the dispatch-path wiring, not scoring).

Asserts post-fix (89.1-02 H4 fix applied):
  - hook returns without raising
  - agent.set_data("confidence_self_report", X) called with a float in [0.0, 1.0]
  - agent.get_data("b5_result") populated with total + recommendation
  - loop_data.params_temporary["b5_result"] NOT required by the hook contract
    (the hook writes to agent slots, not loop_data — tested below)

See test_b5_hook_rca.py for the unit-level regression test that covers the
specific TypeError that caused the dispatch-path failure.
"""
from __future__ import annotations

import pathlib
from typing import Any
from unittest.mock import patch

import pytest
import yaml

VM107_ROOT = pathlib.Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# Production-shaped agent stub (same contract as test_b5_hook_rca.py)
# ---------------------------------------------------------------------------

class _ProductionAgentStub:
    """Mimics production Agent.get_data / set_data contract.

    Agent.get_data(self, field: str) — exactly ONE argument (no default).
    Agent.set_data(self, field: str, value) — TWO positional args.
    """

    def __init__(self, profile: dict):
        self.profile = profile
        self._data: dict[str, Any] = {}

    def get_data(self, field: str):
        return self._data.get(field, None)

    def set_data(self, field: str, value: Any) -> None:
        self._data[field] = value


def _load_profile_yaml() -> dict:
    """Load the actual registry agent profile YAML (same path as api_message.py)."""
    profile_path = VM107_ROOT / "registry" / "agent_profile" / "vm107.macro_investigator.yaml"
    assert profile_path.exists(), (
        f"Agent profile YAML missing at {profile_path}. "
        "This is required for the B5 hook to fire (profile.get('b5_self_eval') check)."
    )
    return yaml.safe_load(profile_path.read_text()) or {}


def _canned_rubric() -> dict:
    """Minimal rubric matching the registry YAML structure."""
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
            "I'm not sure I can answer this confidently — please try a narrower question."
        ),
        "utility_model_routing": {"use_phase_43_1": True},
        "word_cap": {"target": 250, "hard_cap": 400},
    }


# ---------------------------------------------------------------------------
# Realistic investigator answer fixture
# ---------------------------------------------------------------------------

_REALISTIC_INVESTIGATOR_ANSWER = """\
The CPI reading for March 2024 came in at 3.5% YoY, surprising markets with a slight
upside relative to the 3.4% consensus expectation [ref:release:CPIAUCSL-2024-03].
Core CPI ex-food and energy remained sticky at 3.8% [ref:release:CORE_CPI-2024-03],
suggesting that the disinflation trend observed in H2 2023 may be stalling.

The primary driver of the upside was shelter costs, which contributed approximately
0.5 percentage points to the monthly change. This is consistent with lagged rental
renewal cycles rather than a structural re-acceleration of inflation.

Risk interpretation: markets appear to have re-priced rate cut expectations,
with the first Fed cut now priced for September 2024 rather than June [ref:belief:fed-cut-repricing-mar2024].
The correlation between sticky shelter CPI and longer-dated treasury yields remains
elevated, though causation from CPI prints to yield moves is uncertain.
"""


class _LoopDataStub:
    """Minimal loop_data stub with params_temporary dict."""

    def __init__(self, response_text: str):
        self.params_temporary: dict[str, Any] = {
            "current_agent_response": response_text,
        }
        self.last_response: str = ""  # older API, should not be used post-f774359


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestB5DispatchPathIntegration:
    """End-to-end integration test for the B5 hook on the dispatch path.

    Uses the real agent profile YAML (same path as api_message.py), a
    production-shaped agent stub, and realistic loop_data. LLM calls are
    patched to avoid cost in CI.
    """

    def test_run_b5_hook_populates_confidence_self_report_on_dispatch_path(self):
        """run_b5_hook completes without raising and populates confidence_self_report.

        Verifies the full dispatch-path shape end-to-end:
          1. Profile loaded from actual registry YAML (b5_self_eval=True, b5_rubric_id set)
          2. Production agent stub (get_data takes 1 arg only)
          3. loop_data with params_temporary["current_agent_response"] set
          4. load_rubric patched (avoids CapabilityRegistry boot in CI)
          5. _call_utility_model_for_check patched (avoids LLM cost)

        All assertions must pass after the 89.1-02 H4 fix is applied.
        """
        from core.b5.response_self_check_hook import run_b5_hook

        profile = _load_profile_yaml()
        assert profile.get("b5_self_eval") is True, (
            "vm107.macro_investigator YAML must have b5_self_eval: true"
        )
        assert profile.get("b5_rubric_id") == "rubric.macro_investigator_qa", (
            "vm107.macro_investigator YAML must have b5_rubric_id: rubric.macro_investigator_qa"
        )

        agent = _ProductionAgentStub(profile=profile)
        loop_data = _LoopDataStub(response_text=_REALISTIC_INVESTIGATOR_ANSWER)

        canned_scores = {
            "cites_evidence": 0.90,
            "claims_within_cited_evidence": 0.85,
            "acknowledges_uncertainty": 0.80,
            "correlation_not_causation": 0.85,
            "confidence_calibrated_and_concise": 0.85,
        }

        with (
            patch("core.b5.response_self_check_hook.load_rubric", return_value=_canned_rubric()),
            patch(
                "core.b5.rubric_scorer._call_utility_model_for_check",
                side_effect=lambda check_id, **_kw: canned_scores.get(check_id, 0.8),
            ),
        ):
            # Must complete without raising (pre-fix: TypeError from get_data)
            run_b5_hook(agent, loop_data=loop_data)

        # confidence_self_report must be non-null float in [0.0, 1.0]
        score = agent.get_data("confidence_self_report")
        assert score is not None, (
            "confidence_self_report must be non-null. "
            "If None, the hook exited early (rubric load failed or TypeError)."
        )
        assert isinstance(score, float), f"Expected float, got {type(score).__name__}: {score}"
        assert 0.0 <= score <= 1.0, f"Score out of range [0, 1]: {score}"

        # b5_result must be a dict with 'total' and 'recommendation'
        b5_result = agent.get_data("b5_result")
        assert b5_result is not None, (
            "b5_result must be non-null. "
            "api_message.py reads this slot to populate the AskResponse b5_result field."
        )
        assert isinstance(b5_result, dict), f"Expected dict, got {type(b5_result).__name__}"
        assert "total" in b5_result, f"b5_result missing 'total': {b5_result.keys()}"
        assert "recommendation" in b5_result, f"b5_result missing 'recommendation': {b5_result.keys()}"
        assert b5_result["recommendation"] in ("accept", "refine", "reject"), (
            f"Unexpected recommendation: {b5_result['recommendation']}"
        )

        # With all scores ~0.85, weighted total should be well above accept threshold (0.75)
        # total = 0.90*0.30 + 0.85*0.25 + 0.80*0.20 + 0.85*0.15 + 0.85*0.10
        #       = 0.27 + 0.2125 + 0.16 + 0.1275 + 0.085 = 0.855
        assert b5_result["total"] > 0.75, (
            f"Expected total > 0.75 (accept) with canned scores, got {b5_result['total']}"
        )
        assert b5_result["recommendation"] == "accept", (
            f"Expected 'accept' with high canned scores, got {b5_result['recommendation']}"
        )

    def test_run_b5_hook_dispatch_path_low_scores_degrades(self):
        """run_b5_hook with low canned scores routes to degrade.

        Verifies the full hook flow: score below reject_below (0.40) →
        recommendation='reject' → _degrade called → loop_data response replaced.
        """
        from core.b5.response_self_check_hook import run_b5_hook

        profile = _load_profile_yaml()
        agent = _ProductionAgentStub(profile=profile)
        loop_data = _LoopDataStub(response_text="A vague answer with no citations.")

        # All checks score very low (reject)
        low_scores = {
            "cites_evidence": 0.10,
            "claims_within_cited_evidence": 0.10,
            "acknowledges_uncertainty": 0.15,
            "correlation_not_causation": 0.10,
            "confidence_calibrated_and_concise": 0.20,
        }

        with (
            patch("core.b5.response_self_check_hook.load_rubric", return_value=_canned_rubric()),
            patch(
                "core.b5.rubric_scorer._call_utility_model_for_check",
                side_effect=lambda check_id, **_kw: low_scores.get(check_id, 0.1),
            ),
        ):
            run_b5_hook(agent, loop_data=loop_data)

        # Low scores → reject → degrade
        assert agent.get_data("b5_degraded") is True, (
            "Expected b5_degraded=True after low-score rejection"
        )
        assert agent.get_data("confidence_self_report") is not None, (
            "confidence_self_report must be set even on degrade path"
        )
        # loop_data response should be replaced with graceful degradation text
        degraded_response = loop_data.params_temporary.get("current_agent_response", "")
        assert "not sure" in degraded_response.lower() or "confident" in degraded_response.lower(), (
            f"Expected graceful degradation text in loop_data, got: {degraded_response!r}"
        )

    def test_run_b5_hook_dispatch_path_uses_loop_data_response_not_agent_attr(self):
        """Hook reads response from loop_data.params_temporary, not agent attribute.

        Confirms the f774359 fix: the hook prefers
        loop_data.params_temporary["current_agent_response"] over any
        agent.last_response attribute.
        """
        from core.b5.response_self_check_hook import run_b5_hook

        profile = _load_profile_yaml()
        agent = _ProductionAgentStub(profile=profile)
        # Do NOT set agent.last_response (it doesn't exist on Agent in production)

        loop_response = "Answer from loop_data with [ref:release:CPI-2024-03]."
        loop_data = _LoopDataStub(response_text=loop_response)

        # Capture what answer text was actually scored
        scored_answers = []

        def _capture_answer(check_id: str, *, answer: str, **_kw) -> float:
            if not scored_answers:  # capture only on first check
                scored_answers.append(answer)
            return 0.85

        with (
            patch("core.b5.response_self_check_hook.load_rubric", return_value=_canned_rubric()),
            patch(
                "core.b5.rubric_scorer._call_utility_model_for_check",
                side_effect=_capture_answer,
            ),
        ):
            run_b5_hook(agent, loop_data=loop_data)

        assert scored_answers, "No answer was scored — hook may have exited early"
        assert loop_response in scored_answers[0], (
            f"Hook scored wrong answer. Expected loop_data response, got: {scored_answers[0]!r}"
        )
