"""Phase 43.2 Plan 02 — execute_with_fallback unit tests (mocked LiteLLM).

All xfail markers REMOVED in Plan 02 (was Wave 0 scaffold). Tests are now GREEN.

Coverage map (CONTEXT.md + VALIDATION.md):
  TestExec  -> ROUTER-FAILOVER-EXEC-01
  TestCatch -> ROUTER-FAILOVER-CATCH-01
  TestLog   -> ROUTER-FAILOVER-LOG-01
  TestCost  -> ROUTER-FAILOVER-COST-01
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, call

import litellm.exceptions
import pytest


# ---- helpers ----------------------------------------------------------------

def _make_decision(primary: str = "primary-model", fallback: list[str] | None = None):
    """Construct a minimal RoutingDecision-like object for testing.

    Uses the real RoutingDecision schema to ensure schema compat.
    """
    from core.routing.schemas import RoutingDecision
    return RoutingDecision(
        task_id="test-task-id",
        goal_id="test-goal-id",
        agent_id="agent_zero",
        task_type="default",
        primary=primary,
        selected_model=primary,
        fallback=fallback or [],
        reason=[],
        decision_time_ms=1.0,
        force_local=False,
        path="chat",
    )


def _api_conn_err(model: str = "primary-model") -> litellm.exceptions.APIConnectionError:
    return litellm.exceptions.APIConnectionError(
        message="Connection refused",
        llm_provider="test",
        model=model,
    )


def _rate_limit_err(model: str = "primary-model") -> litellm.exceptions.RateLimitError:
    return litellm.exceptions.RateLimitError(
        message="Rate limited",
        llm_provider="test",
        model=model,
    )


# =============================================================================
# TestExec — ROUTER-FAILOVER-EXEC-01
# =============================================================================

class TestExec:
    """ROUTER-FAILOVER-EXEC-01: execute_with_fallback iterates chain on retryable errors."""

    @pytest.mark.asyncio
    async def test_primary_succeeds_no_fallback(self):
        """Primary returns successfully -> chain_index=0, fallback_used=False."""
        from core.routing.failover_executor import execute_with_fallback

        decision = _make_decision(primary="gpt-4o", fallback=["deepseek-v4-flash"])
        mock_call = AsyncMock(return_value=("hello", ""))
        set_model = MagicMock()
        agent_data = {}

        result = await execute_with_fallback(
            call_fn=mock_call,
            chain=["gpt-4o", "deepseek-v4-flash"],
            decision=decision,
            set_model_name=set_model,
            agent_data=agent_data,
            decision_id="test-exec-01",
            a0_retry_attempts=0,
        )

        assert result == ("hello", "")
        assert mock_call.call_count == 1
        assert set_model.call_args_list == [call("gpt-4o")]
        # Only success tag appended (no failure tags)
        assert decision.reason == ["completed:gpt-4o"]
        # agent_data stash populated
        assert agent_data["_router_failover_result"] == {
            "model": "gpt-4o",
            "chain_index": 0,
            "fallback_used": False,
            "attempt_count": 1,
        }

    @pytest.mark.asyncio
    async def test_primary_fails_secondary_succeeds(self):
        """Primary raises APIConnectionError -> secondary called -> chain_index=1, fallback_used=True."""
        from core.routing.failover_executor import execute_with_fallback

        decision = _make_decision(primary="primary-model", fallback=["secondary-model"])
        mock_call = AsyncMock(side_effect=[
            _api_conn_err("primary-model"),
            ("response_text", "reasoning_text"),
        ])
        set_model = MagicMock()
        agent_data = {}

        result = await execute_with_fallback(
            call_fn=mock_call,
            chain=["primary-model", "secondary-model"],
            decision=decision,
            set_model_name=set_model,
            agent_data=agent_data,
            decision_id="test-exec-02",
            a0_retry_attempts=0,
        )

        assert result == ("response_text", "reasoning_text")
        assert mock_call.call_count == 2
        # set_model called for each attempt in order
        assert set_model.call_args_list == [call("primary-model"), call("secondary-model")]
        # Reason chain: failure tag + fallback-to tag + success tag
        assert decision.reason == [
            "primary_failed:APIConnectionError",
            "fallback_to:secondary-model",
            "completed:secondary-model",
        ]
        # agent_data stash reflects ACTUAL model called
        assert agent_data["_router_failover_result"] == {
            "model": "secondary-model",
            "chain_index": 1,
            "fallback_used": True,
            "attempt_count": 2,
        }

    @pytest.mark.asyncio
    async def test_chain_exhausted(self):
        """All chain entries fail -> RouterChainExhaustedError with all attempts populated."""
        from core.routing.failover_executor import execute_with_fallback
        from core.routing.exceptions import RouterChainExhaustedError

        decision = _make_decision(primary="m0", fallback=["m1", "m2"])
        errors = [
            _api_conn_err("m0"),
            _api_conn_err("m1"),
            _api_conn_err("m2"),
        ]
        mock_call = AsyncMock(side_effect=errors)
        set_model = MagicMock()
        agent_data = {}

        with pytest.raises(RouterChainExhaustedError) as exc_info:
            await execute_with_fallback(
                call_fn=mock_call,
                chain=["m0", "m1", "m2"],
                decision=decision,
                set_model_name=set_model,
                agent_data=agent_data,
                decision_id="test-exec-03",
                a0_retry_attempts=0,
            )

        exc = exc_info.value
        # All 3 attempts recorded
        assert len(exc.attempts) == 3
        # Exception OBJECTS preserved (not strings) — isinstance semantics work
        assert isinstance(exc.attempts[0]["error"], litellm.exceptions.APIConnectionError)
        assert isinstance(exc.attempts[1]["error"], litellm.exceptions.APIConnectionError)
        assert isinstance(exc.attempts[2]["error"], litellm.exceptions.APIConnectionError)
        # Model names preserved in attempts
        assert exc.attempts[0]["model"] == "m0"
        assert exc.attempts[1]["model"] == "m1"
        assert exc.attempts[2]["model"] == "m2"
        # chain_index preserved
        assert exc.attempts[0]["chain_index"] == 0
        assert exc.attempts[1]["chain_index"] == 1
        assert exc.attempts[2]["chain_index"] == 2
        # Reason chain ends with chain_exhausted
        assert "chain_exhausted" in decision.reason
        # agent_data NOT populated on exhaustion
        assert "_router_failover_result" not in agent_data


# =============================================================================
# TestCatch — ROUTER-FAILOVER-CATCH-01
# =============================================================================

class TestCatch:
    """ROUTER-FAILOVER-CATCH-01: retryable vs non-retryable exception taxonomy."""

    @pytest.mark.asyncio
    async def test_non_retryable_authentication_error_reraises(self):
        """AuthenticationError on primary -> immediate re-raise, NO fallback attempt."""
        from core.routing.failover_executor import execute_with_fallback

        decision = _make_decision(primary="primary-model", fallback=["fallback-model"])
        auth_err = litellm.exceptions.AuthenticationError(
            message="Invalid API key",
            llm_provider="test",
            model="primary-model",
        )
        mock_call = AsyncMock(side_effect=auth_err)
        set_model = MagicMock()

        with pytest.raises(litellm.exceptions.AuthenticationError):
            await execute_with_fallback(
                call_fn=mock_call,
                chain=["primary-model", "fallback-model"],
                decision=decision,
                set_model_name=set_model,
                a0_retry_attempts=0,
            )

        # Only one attempt made (no fallback)
        assert mock_call.call_count == 1
        # set_model called once for primary only
        assert set_model.call_args_list == [call("primary-model")]
        # NO failure tags appended (non-retryable re-raises immediately without appending)
        assert decision.reason == []

    @pytest.mark.asyncio
    async def test_context_window_exceeded_non_retryable(self):
        """ContextWindowExceededError (subclass of BadRequestError) re-raises — does NOT fallback."""
        from core.routing.failover_executor import execute_with_fallback

        decision = _make_decision(primary="primary-model", fallback=["fallback-model"])
        ctx_err = litellm.exceptions.ContextWindowExceededError(
            message="Input too long",
            llm_provider="test",
            model="primary-model",
        )
        mock_call = AsyncMock(side_effect=ctx_err)
        set_model = MagicMock()

        with pytest.raises(litellm.exceptions.ContextWindowExceededError):
            await execute_with_fallback(
                call_fn=mock_call,
                chain=["primary-model", "fallback-model"],
                decision=decision,
                set_model_name=set_model,
                a0_retry_attempts=0,
            )

        # Only one attempt (ContextWindowExceeded is non-retryable — caller must truncate)
        assert mock_call.call_count == 1
        # No reason tags appended (non-retryable exits before appending)
        assert decision.reason == []

        # Verify it is indeed a subclass of BadRequestError (safety check)
        assert isinstance(ctx_err, litellm.exceptions.BadRequestError)

    @pytest.mark.asyncio
    async def test_notfound_error_is_retryable(self):
        """NotFoundError on primary -> fallback DOES fire (NotFound is retryable per spec)."""
        from core.routing.failover_executor import execute_with_fallback

        decision = _make_decision(primary="missing-model", fallback=["deepseek-v4-flash"])
        notfound_err = litellm.exceptions.NotFoundError(
            message="Model not found",
            llm_provider="test",
            model="missing-model",
        )
        mock_call = AsyncMock(side_effect=[
            notfound_err,
            ("fallback response", ""),
        ])
        set_model = MagicMock()

        result = await execute_with_fallback(
            call_fn=mock_call,
            chain=["missing-model", "deepseek-v4-flash"],
            decision=decision,
            set_model_name=set_model,
            a0_retry_attempts=0,
        )

        assert result == ("fallback response", "")
        # Both models attempted
        assert mock_call.call_count == 2
        # NotFoundError IS retryable — fallback_to tag appears
        assert "primary_failed:NotFoundError" in decision.reason
        assert "fallback_to:deepseek-v4-flash" in decision.reason
        assert "completed:deepseek-v4-flash" in decision.reason


# =============================================================================
# TestLog — ROUTER-FAILOVER-LOG-01
# =============================================================================

class TestLog:
    """ROUTER-FAILOVER-LOG-01: reason chain extension with all 4 tag types."""

    @pytest.mark.asyncio
    async def test_reason_chain_tags_in_order(self):
        """Successful failover reason chain: [..., primary_failed:X, fallback_to:Y, completed:Y]."""
        from core.routing.failover_executor import execute_with_fallback

        decision = _make_decision(primary="primary-model", fallback=["secondary-model"])
        mock_call = AsyncMock(side_effect=[
            _api_conn_err("primary-model"),
            ("ok", ""),
        ])

        await execute_with_fallback(
            call_fn=mock_call,
            chain=["primary-model", "secondary-model"],
            decision=decision,
            set_model_name=MagicMock(),
            a0_retry_attempts=0,
        )

        # All 3 tag types present in correct order
        assert decision.reason[0] == "primary_failed:APIConnectionError"
        assert decision.reason[1] == "fallback_to:secondary-model"
        assert decision.reason[2] == "completed:secondary-model"
        assert len(decision.reason) == 3

    @pytest.mark.asyncio
    async def test_reason_chain_exhausted_tag(self):
        """Exhausted chain reason chain ends with 'chain_exhausted' tag."""
        from core.routing.failover_executor import execute_with_fallback
        from core.routing.exceptions import RouterChainExhaustedError

        decision = _make_decision(primary="m0", fallback=["m1"])
        mock_call = AsyncMock(side_effect=[
            _api_conn_err("m0"),
            _rate_limit_err("m1"),
        ])

        with pytest.raises(RouterChainExhaustedError):
            await execute_with_fallback(
                call_fn=mock_call,
                chain=["m0", "m1"],
                decision=decision,
                set_model_name=MagicMock(),
                a0_retry_attempts=0,
            )

        # Reason chain: failure tags + chain_exhausted at end
        assert decision.reason[-1] == "chain_exhausted"
        # primary_failed tags for both models
        assert "primary_failed:APIConnectionError" in decision.reason
        assert "primary_failed:RateLimitError" in decision.reason
        # fallback_to tag for m1 (before m1 attempt)
        assert "fallback_to:m1" in decision.reason
        # NO completed tag (chain exhausted before success)
        assert not any(r.startswith("completed:") for r in decision.reason)


# =============================================================================
# TestCost — ROUTER-FAILOVER-COST-01
# =============================================================================

class TestCost:
    """ROUTER-FAILOVER-COST-01: CostRecord captures actual model + chain_index + fallback_used."""

    @pytest.mark.asyncio
    async def test_cost_record_on_fallback(self):
        """After fallback to secondary: agent_data stash has model=secondary, chain_index=1, fallback_used=True."""
        from core.routing.failover_executor import execute_with_fallback

        decision = _make_decision(primary="primary-model", fallback=["secondary-model"])
        mock_call = AsyncMock(side_effect=[
            _api_conn_err("primary-model"),
            ("ok response", "ok reasoning"),
        ])
        agent_data = {}

        result = await execute_with_fallback(
            call_fn=mock_call,
            chain=["primary-model", "secondary-model"],
            decision=decision,
            set_model_name=MagicMock(),
            agent_data=agent_data,
            a0_retry_attempts=0,
        )

        assert result == ("ok response", "ok reasoning")
        # CostRecord carrier populated with ACTUAL model (not decision.primary)
        failover_result = agent_data["_router_failover_result"]
        assert failover_result["model"] == "secondary-model"      # actual model, NOT decision.primary
        assert failover_result["chain_index"] == 1               # fallback position
        assert failover_result["fallback_used"] is True
        assert failover_result["attempt_count"] == 2             # 1 primary attempt + 1 fallback

    @pytest.mark.asyncio
    async def test_cost_record_only_on_success_not_per_attempt(self):
        """One CostRecord carrier entry per call (the success). Per-attempt failures don't populate it."""
        from core.routing.failover_executor import execute_with_fallback

        decision = _make_decision(primary="m0", fallback=["m1", "m2"])
        # m0 and m1 fail; m2 succeeds
        mock_call = AsyncMock(side_effect=[
            _api_conn_err("m0"),
            _rate_limit_err("m1"),
            ("success", ""),
        ])
        agent_data = {}

        await execute_with_fallback(
            call_fn=mock_call,
            chain=["m0", "m1", "m2"],
            decision=decision,
            set_model_name=MagicMock(),
            agent_data=agent_data,
            a0_retry_attempts=0,
        )

        # ONE result stashed (not one per attempt — per CONTEXT.md "ONE CostRecord per call")
        assert "_router_failover_result" in agent_data
        failover_result = agent_data["_router_failover_result"]

        # Only the SUCCESS model recorded
        assert failover_result["model"] == "m2"
        assert failover_result["chain_index"] == 2
        assert failover_result["fallback_used"] is True
        assert failover_result["attempt_count"] == 3  # 3 attempts total

        # Verify attempt multiplication prevention: call_fn called exactly 3 times
        # (not 3×3=9 which would happen if a0_retry_attempts!=0 were internally retried)
        assert mock_call.call_count == 3
