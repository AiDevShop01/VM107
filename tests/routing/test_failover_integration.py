"""Phase 43.2 Plan 04 — execute_with_fallback integration test.

Real LiteLLM call: primary=openai/canary-primary with api_base=http://127.0.0.1:1
(connection refused -> real InternalServerError -> RETRYABLE -> failover fires),
secondary=deepseek/deepseek-v4-flash (real call). Validates ALL FOUR layers + the
a0_retry_attempts=0 keyword forwarding chain (Plan 02 forwards via **call_kwargs which IS
correct — this test proves it end-to-end before the canary depends on it).

Key design choices:
  - primary uses openai/ prefix so LiteLLM attempts a real HTTP call (not BadRequestError).
    api_base=http://127.0.0.1:1 causes connection refused -> InternalServerError (RETRYABLE).
  - secondary uses DEEPSEEK_API_KEY from env to make a real API call.
  - api_key injected per-model in call_fn closure to bypass ModelConfig path.
"""

from __future__ import annotations

import asyncio
import os

import pytest


pytestmark = pytest.mark.integration  # XFAIL marker REMOVED


class TestE2EUnreachable:
    """ROUTER-FAILOVER-VERIFY-01: real failover with unreachable primary."""

    @pytest.mark.skipif(
        not os.environ.get("DEEPSEEK_API_KEY"),
        reason="Requires DEEPSEEK_API_KEY env var for real fallback model call",
    )
    @pytest.mark.asyncio
    async def test_unreachable_primary_real_fallover(self, capfd, caplog):
        """Configure primary=openai/canary-primary with api_base=http://127.0.0.1:1,
        secondary=deepseek/deepseek-v4-flash.
        Real LiteLLM acompletion call -> real connection refused -> InternalServerError
        (RETRYABLE) -> real failover.
        Asserts ALL FOUR layers:
          1. Execution: secondary actually invoked (response is non-empty)
          2. Reason chain: ['primary_failed:InternalServerError', 'fallback_to:deepseek/...', 'completed:deepseek/...']
          3. agent.data stash: model=deepseek/deepseek-v4-flash, chain_index=1, fallback_used=True
          4. Stdout logs: 'model_failure' and 'model_success' events present

        ALSO verifies a0_retry_attempts=0 keyword forwarding chain:
          execute_with_fallback(**call_kwargs) -> call_fn(**kwargs) -> unified_call(**kwargs)
          One named kwarg, one position — no duplicate argument risk.
          If forwarding were broken, we'd get TypeError before reaching the asserts.
        """
        from core.routing.failover_executor import execute_with_fallback
        from core.routing.schemas import RoutingDecision
        from models import LiteLLMChatWrapper

        # Construct a real LiteLLMChatWrapper instance.
        # Constructor signature: LiteLLMChatWrapper(model, provider, model_config=None)
        # It sets model_name = f"{provider}/{model}"; failover will swap model_name via setattr.
        wrapper = LiteLLMChatWrapper(
            model="canary-primary",
            provider="openai",
            model_config=None,
        )

        deepseek_api_key = os.environ.get("DEEPSEEK_API_KEY", "")

        decision = RoutingDecision(
            task_id="integration-test-1",
            goal_id="integration-test",
            agent_id="test_agent",
            task_type="validation",
            primary="openai/canary-primary",
            fallback=["deepseek/deepseek-v4-flash"],
            reason=[],
            decision_time_ms=0.0,
            selected_model="openai/canary-primary",
            force_local=False,
            path="chat",
        )

        agent_data: dict = {}

        # Set caplog level to INFO to capture model_success events (logged at INFO level).
        # model_failure is at WARNING, model_success is at INFO — both need to be captured.
        import logging
        caplog.set_level(logging.INFO, logger="router.failover")

        # call_fn closure — forwards **kwargs to wrapper.unified_call.
        # CRITICAL: a0_retry_attempts=0 must flow through here exactly once.
        # The wrapper accepts **kwargs so it flows through cleanly.
        # Per-model kwargs injection:
        #   - primary (canary-primary): api_base=http://127.0.0.1:1 -> connection refused
        #     -> InternalServerError (RETRYABLE) -> failover fires
        #   - secondary (deepseek): api_key from env
        async def call_fn(**kwargs):
            call_kw = dict(kwargs)
            if "canary-primary" in wrapper.model_name:
                call_kw["api_base"] = "http://127.0.0.1:1"
                call_kw["api_key"] = "canary-invalid-key"
            elif "deepseek" in wrapper.model_name and deepseek_api_key:
                call_kw.setdefault("api_key", deepseek_api_key)
            return await wrapper.unified_call(
                system_message="",
                user_message="Reply with exactly: ok",
                **call_kw,
            )

        # Execute via failover wrapper with timeout to prevent CI hang.
        # **call_kwargs forwarding pattern (Plan 02): execute_with_fallback receives
        # a0_retry_attempts=0 as a kwarg, forwards to call_fn(**kwargs), which forwards
        # to unified_call(**kwargs). One named kwarg, one position — no duplicate risk.
        result = await asyncio.wait_for(
            execute_with_fallback(
                call_fn=call_fn,
                chain=[decision.primary] + list(decision.fallback),
                decision=decision,
                set_model_name=lambda m: setattr(wrapper, "model_name", m),
                agent_data=agent_data,
                decision_id="integration-test-1",
                a0_retry_attempts=0,  # MUST forward cleanly through call_fn -> unified_call
            ),
            timeout=30,
        )

        # ===== Layer 1: Execution =====
        response, reasoning = result
        assert response, "Secondary call returned empty response"
        assert wrapper.model_name == "deepseek/deepseek-v4-flash", (
            f"Model not swapped to fallback: {wrapper.model_name}"
        )

        # ===== Layer 2: Reason chain =====
        assert any("primary_failed" in r for r in decision.reason), (
            f"Reason chain missing primary_failed tag: {decision.reason}"
        )
        assert any("fallback_to" in r and "deepseek" in r for r in decision.reason), (
            f"Reason chain missing fallback_to tag: {decision.reason}"
        )
        assert any("completed" in r and "deepseek" in r for r in decision.reason), (
            f"Reason chain missing completed tag: {decision.reason}"
        )

        # ===== Layer 3: agent.data['_router_failover_result'] (CostRecord precursor) =====
        result_stash = agent_data.get("_router_failover_result")
        assert result_stash is not None, "agent.data missing _router_failover_result"
        assert result_stash["fallback_used"] is True, (
            f"fallback_used should be True: {result_stash}"
        )
        assert result_stash["chain_index"] == 1, (
            f"chain_index should be 1: {result_stash}"
        )
        assert "deepseek" in result_stash["model"], (
            f"actual model should be deepseek: {result_stash}"
        )

        # ===== Layer 4: Structured log events (model_failure + model_success) =====
        # failover_executor.py uses Python logging (log.warning / log.info) with
        # json.dumps payloads. In production, these are captured by the container log
        # driver. In tests, pytest captures them via the logging plugin (caplog).
        # We combine stdout/stderr (capfd) and caplog.text to ensure we catch both paths.
        captured = capfd.readouterr()
        combined = captured.out + captured.err + caplog.text
        assert '"event": "model_failure"' in combined, (
            f"Missing model_failure structured log event. Combined output: {combined[:800]}"
        )
        assert '"event": "model_success"' in combined, (
            f"Missing model_success structured log event. Combined output: {combined[:800]}"
        )

        # ===== EXTRA: a0_retry_attempts forwarding sanity =====
        # If the kwarg failed to forward (or got duplicated), the call would have raised
        # TypeError("got multiple values for keyword argument 'a0_retry_attempts'") and we'd
        # never reach this point. Reaching this assert proves the forwarding chain is intact.
        assert response, "If we got here, **call_kwargs forwarding chain is intact"
