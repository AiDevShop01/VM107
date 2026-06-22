"""Phase 89.1 Plan 02 — B5 hook RCA regression tests.

Round 1 root cause (captured 2026-06-22 03:11 UTC, 89.1-02-B5-RCA-LOG.md):
    TypeError: Agent.get_data() takes 2 positional arguments but 3 were given
    File "/a0/core/b5/response_self_check_hook.py", line 79, in run_b5_hook
        util_spent: float = agent.get_data("b5_utility_model_spend", 0.0) or 0.0
    Fixed in 6bc3c53: change to `agent.get_data("key") or default` pattern.

Round 2 root cause (captured 2026-06-22 17:00 UTC, 89.1-02-B5-RCA-LOG.md Round 2):
    ImportError: cannot import name 'call_utility_model' from 'helpers.call_llm'
    File "/a0/core/b5/rubric_scorer.py", in _call_utility_model_for_check
        from helpers.call_llm import call_utility_model
    `call_utility_model` was never defined in helpers/call_llm.py. All 5 checks return
    the 0.5 fail-open default → total 0.5 → refine → second pass (also 0.5) → b5_degrade.
    Fix: thread `utility_model_fn` callable from agent through score_answer into scorer.

Tests:
1. test_b5_hook_repros_dispatch_path_failure (Round 1 — must remain passing)
   — Uses _ProductionAgentStub (get_data accepts 1 arg only). Was FAIL pre-6bc3c53,
     PASS after.

2. test_b5_hook_stub_get_data_raises_on_two_args (Round 1 meta-test — must remain passing)

3. test_b5_scorer_check_returns_half_without_utility_fn (Round 2 RED)
   — Calls _call_utility_model_for_check WITHOUT utility_model_fn. On pre-fix code the
     broken import fires (ImportError caught, returns 0.5). On post-fix code the function
     signature has utility_model_fn=None which also returns 0.5 with a warning. Either
     way this is the failure mode — asserts 0.5 is returned (behaviour preserved).
     The RED test is the next one.

4. test_b5_scorer_uses_utility_model_fn_when_provided (Round 2 RED → GREEN)
   — Calls _call_utility_model_for_check WITH a canned utility_model_fn returning 0.9.
     Pre-fix: function signature has no utility_model_fn param → TypeError on call.
     Post-fix: utility_model_fn is called, returns 0.9.

5. test_b5_hook_routes_utility_model_fn_through_scorer (Round 2 RED → GREEN)
   — Calls run_b5_hook with an agent that has call_utility_model returning 0.9 for all
     checks. Pre-fix: scorer still uses broken import → all 0.5 → degrade.
     Post-fix: scorer receives the callable → all 0.9 → accept.

6. test_b5_hook_no_silent_swallow_on_dispatch_path (Round 1 defensive — must remain passing)
"""
from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared: production-shaped agent stub
# ---------------------------------------------------------------------------

class _ProductionAgentStub:
    """Mimics the production Agent.get_data / set_data contract.

    Agent.get_data(self, field: str) — exactly ONE argument, returns None when absent.
    Agent.set_data(self, field: str, value) — TWO positional args.

    This is the key difference from MagicMock which accepts any arity.
    """

    def __init__(self, profile: dict):
        self.profile = profile
        self._data: dict[str, Any] = {}

    def get_data(self, field: str):  # NO default parameter — matches agent.py:680
        """Single-argument get_data matching production Agent contract."""
        return self._data.get(field, None)

    def set_data(self, field: str, value: Any) -> None:  # matches agent.py:683
        self._data[field] = value


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


def _make_loop_data_stub(response_text: str) -> MagicMock:
    """Return a loop_data stub with params_temporary["current_agent_response"] set."""
    loop_data = MagicMock()
    loop_data.params_temporary = {"current_agent_response": response_text}
    return loop_data


# ---------------------------------------------------------------------------
# Test 1: Reproduces the dispatch-path failure (RED on pre-fix, GREEN after fix)
# ---------------------------------------------------------------------------

class TestB5HookReproDispatchPathFailure:
    """Test that uses the production-shaped agent stub to expose the get_data bug.

    This test MUST FAIL on pre-fix code (TypeError from extra argument to get_data)
    and PASS after the fix (agent.get_data("key") or default pattern).
    """

    def test_b5_hook_repros_dispatch_path_failure(self):
        """Run run_b5_hook with a production-shaped agent stub.

        Pre-fix: raises TypeError at agent.get_data("b5_utility_model_spend", 0.0)
        Post-fix: returns normally, confidence_self_report is set.

        Uses a canned rubric (no registry call) and patched _call_utility_model_for_check
        (no LLM call) to isolate the get_data contract bug.
        """
        from core.b5.response_self_check_hook import run_b5_hook

        agent = _ProductionAgentStub(profile={
            "id": "vm107.macro_investigator",
            "b5_self_eval": True,
            "b5_rubric_id": "rubric.macro_investigator_qa",
            "cost_budget_per_invocation": {
                "chat_model_usd": 0.50,
                "utility_model_usd": 0.20,
            },
        })

        loop_data = _make_loop_data_stub(
            "Gold rose [ref:release:CPI-2026-06-10] because real rates stayed negative."
        )

        # Patch load_rubric (used by response_self_check_hook) and
        # _call_utility_model_for_check (used by rubric_scorer) to keep this
        # test fast and hermetic — we are only testing the get_data contract,
        # not the LLM call path.
        canned_scores = {
            "cites_evidence": 0.90,
            "claims_within_cited_evidence": 0.85,
            "acknowledges_uncertainty": 0.80,
            "correlation_not_causation": 0.85,
            "confidence_calibrated_and_concise": 0.90,
        }

        with (
            patch("core.b5.response_self_check_hook.load_rubric", return_value=_canned_rubric()),
            patch(
                "core.b5.rubric_scorer._call_utility_model_for_check",
                side_effect=lambda check_id, **_kw: canned_scores.get(check_id, 0.8),
            ),
        ):
            # This MUST succeed (post-fix). Pre-fix code raises TypeError here:
            #   agent.get_data("b5_utility_model_spend", 0.0)
            run_b5_hook(agent, loop_data=loop_data)

        # Post-fix: confidence_self_report must be a float in [0.0, 1.0]
        score = agent.get_data("confidence_self_report")
        assert score is not None, (
            "confidence_self_report must be non-null after run_b5_hook. "
            "Pre-fix: hook raises TypeError before ever writing this slot. "
            "If this assert fires, the get_data contract fix was not applied."
        )
        assert isinstance(score, float), f"Expected float, got {type(score)}"
        assert 0.0 <= score <= 1.0, f"Expected score in [0.0, 1.0], got {score}"

        # b5_result must be populated
        b5_result = agent.get_data("b5_result")
        assert b5_result is not None, "b5_result must be non-null after run_b5_hook"
        assert "total" in b5_result, f"b5_result missing 'total' key: {b5_result}"
        assert "recommendation" in b5_result, f"b5_result missing 'recommendation' key: {b5_result}"

    def test_b5_hook_stub_get_data_raises_on_two_args(self):
        """Confirm the stub accurately models the production TypeError.

        This is a meta-test proving that _ProductionAgentStub.get_data correctly
        raises TypeError when called with two arguments (same as agent.py line 680).
        If this test fails, the stub is wrong and so is the regression test above.
        """
        stub = _ProductionAgentStub(profile={})
        # Should be fine with one arg:
        stub.get_data("some_key")
        # Must raise TypeError with two args (mirroring the production bug):
        with pytest.raises(TypeError):
            stub.get_data("some_key", "default_value")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Tests 3–5: Round 2 regression — utility_model_fn threading
# ---------------------------------------------------------------------------

class TestB5ScorerUtilityModelFn:
    """Round 2: Test that _call_utility_model_for_check uses utility_model_fn.

    Pre-fix: function signature has no utility_model_fn parameter.
    Post-fix: utility_model_fn is accepted and called when provided.
    """

    def test_b5_scorer_check_returns_half_without_utility_fn(self):
        """Without utility_model_fn, check returns 0.5 (fail-open default).

        This is the current broken behaviour: the ImportError from
        `from helpers.call_llm import call_utility_model` is caught and
        returns 0.5. After the fix, calling without utility_model_fn still
        returns 0.5 (same fail-open behaviour, different code path).

        This test documents the fail-open contract — it must pass both
        before and after the fix.
        """
        from core.b5.rubric_scorer import _call_utility_model_for_check

        result = _call_utility_model_for_check(
            "cites_evidence",
            check_description="Cites specific evidence sources",
            answer="The CPI rose in March 2024.",
            prompt_context={},
        )
        # Without a real utility model, must return 0.5 (fail-open)
        assert result == 0.5, (
            f"Expected 0.5 fail-open score, got {result}. "
            "Both pre-fix (ImportError) and post-fix (no fn provided) should return 0.5."
        )

    def test_b5_scorer_uses_utility_model_fn_when_provided(self):
        """With utility_model_fn, check uses it and returns its result.

        PRE-FIX STATE: _call_utility_model_for_check has NO utility_model_fn
        parameter. This call raises TypeError: unexpected keyword argument.

        POST-FIX STATE: utility_model_fn is accepted and called; returns 0.9.
        """
        from core.b5.rubric_scorer import _call_utility_model_for_check

        def _canned_fn(prompt: str, **_kw) -> str:
            """Synchronous callable returning a parseable float string."""
            return "0.9"

        # Pre-fix: TypeError because utility_model_fn is not in the signature.
        # Post-fix: returns 0.9 (parsed from _canned_fn's return).
        result = _call_utility_model_for_check(
            "cites_evidence",
            check_description="Cites specific evidence sources",
            answer="The CPI rose 3.5% in March 2024 [ref:release:CPIAUCSL-2024-03].",
            prompt_context={},
            utility_model_fn=_canned_fn,
        )
        assert result == pytest.approx(0.9, abs=0.01), (
            f"Expected 0.9 from utility_model_fn, got {result}. "
            "Pre-fix: TypeError (no utility_model_fn param). "
            "Post-fix: canned fn returns '0.9' → parsed to 0.9."
        )


class TestB5HookRoutesUtilityModelFn:
    """Round 2: Test that run_b5_hook threads utility_model_fn through to scorer.

    Pre-fix: scorer always uses the broken helpers.call_llm import → all 0.5 → degrade.
    Post-fix: scorer receives the callable from agent.call_utility_model → real scores.
    """

    def test_b5_hook_routes_utility_model_fn_through_scorer(self):
        """run_b5_hook with an agent that has call_utility_model gets real scores.

        Agent stub has call_utility_model() returning "0.9" for all prompts.
        Pre-fix: scorer ignores agent.call_utility_model, uses broken import → 0.5
                 scores → total 0.5 → refine → second 0.5 → b5_degrade.
        Post-fix: scorer receives the callable → all 0.9 → total 0.9 → accept.

        We detect the failure mode by checking recommendation == 'accept' after fix.
        Pre-fix recommendation will be 'refine' (first call) or 'reject' (degrade),
        NOT 'accept'.
        """
        from core.b5.response_self_check_hook import run_b5_hook

        class _AgentWithUtilityModel(_ProductionAgentStub):
            """Agent stub that also has a synchronous call_utility_model."""

            def call_utility_model(self, prompt: str, **_kw) -> str:
                """Synchronous utility model returning high-confidence score."""
                return "0.9"

        agent = _AgentWithUtilityModel(profile={
            "id": "vm107.macro_investigator",
            "b5_self_eval": True,
            "b5_rubric_id": "rubric.macro_investigator_qa",
            "cost_budget_per_invocation": {
                "chat_model_usd": 0.50,
                "utility_model_usd": 0.20,
            },
        })

        loop_data = _make_loop_data_stub(
            "The CPI for March 2024 was 3.5% YoY [ref:release:CPIAUCSL-2024-03]. "
            "Core CPI remained at 3.8% [ref:release:CORE_CPI-2024-03]. "
            "The correlation between shelter CPI and yields is noted though causation is uncertain."
        )

        with patch("core.b5.response_self_check_hook.load_rubric", return_value=_canned_rubric()):
            # Do NOT patch _call_utility_model_for_check — that's what we're testing.
            run_b5_hook(agent, loop_data=loop_data)

        b5_result = agent.get_data("b5_result")
        assert b5_result is not None, "b5_result must be non-null"

        # Pre-fix: all checks return 0.5 → total 0.5 → 'refine' (then degrade).
        # Post-fix: agent.call_utility_model returns "0.9" → total ~0.9 → 'accept'.
        recommendation = b5_result.get("recommendation")
        total = b5_result.get("total", 0.0)
        assert recommendation == "accept", (
            f"Expected 'accept' when agent.call_utility_model returns '0.9'. "
            f"Got recommendation='{recommendation}', total={total:.3f}. "
            "Pre-fix: scorer uses broken import → 0.5 → 'refine'/'reject'. "
            "Post-fix: scorer uses agent.call_utility_model → 0.9 → 'accept'."
        )
        assert total > 0.75, (
            f"Expected total > 0.75 (accept threshold), got {total:.3f}"
        )


# ---------------------------------------------------------------------------
# Test 6: Defensive swallow test (already passing from f774359)
# ---------------------------------------------------------------------------

class TestB5HookNoSilentSwallow:
    """Confirm that B5SelfCheckExtension.execute does NOT re-raise on hook failure.

    The extension wraps run_b5_hook in try/except, logs at ERROR with exc_info=True,
    and continues. This defensive contract must stay intact even after the fix,
    because other future callers of run_b5_hook may encounter unexpected errors.
    """

    def test_b5_hook_no_silent_swallow_on_dispatch_path(self, caplog):
        """Extension execute() logs the error and does not re-raise.

        Injects a synthetic RuntimeError into run_b5_hook to confirm the
        swallow-and-log behavior of B5SelfCheckExtension.execute.
        """
        import asyncio
        from extensions.python.response_self_check._10_b5_self_check import B5SelfCheckExtension

        agent = MagicMock()
        agent.profile = {
            "id": "vm107.macro_investigator",
            "b5_self_eval": True,
        }
        loop_data = _make_loop_data_stub("Some investigator answer.")

        ext = B5SelfCheckExtension(agent=agent)

        # The extension does `from core.b5.response_self_check_hook import run_b5_hook`
        # at module load time, so the correct patch target is the name in the extension's
        # own module namespace.
        ext_logger = "extensions.python.response_self_check._10_b5_self_check"
        with (
            patch(
                "extensions.python.response_self_check._10_b5_self_check.run_b5_hook",
                side_effect=RuntimeError("synthetic_test_error"),
            ),
            caplog.at_level(logging.ERROR, logger=ext_logger),
        ):
            # Should NOT raise — extension swallows the error
            asyncio.run(ext.execute(agent=agent, loop_data=loop_data))

        # Must have logged the error — the message format is:
        #   "b5_self_check_failed profile=<id> error=RuntimeError: synthetic_test_error"
        error_records = [
            r for r in caplog.records
            if r.levelno == logging.ERROR and "b5_self_check_failed" in r.getMessage()
        ]
        assert len(error_records) >= 1, (
            f"Expected at least 1 ERROR log with 'b5_self_check_failed'. "
            f"caplog.records: {[(r.name, r.levelno, r.getMessage()) for r in caplog.records]}"
        )
        # exc_info=True means the exception is attached to the log record
        error_rec = error_records[0]
        assert error_rec.exc_info is not None, (
            "Expected exc_info to be set (exc_info=True in the logger call). "
            "This ensures monitoring captures the full traceback."
        )
