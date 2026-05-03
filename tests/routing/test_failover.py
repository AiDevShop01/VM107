"""Phase 43.2 Plan 02 — execute_with_fallback unit tests (mocked LiteLLM).

Wave 0 status: All tests xfail. Plan 02 implements the body and removes xfail markers
to bring tests GREEN.

Coverage map (CONTEXT.md + VALIDATION.md):
  TestExec  -> ROUTER-FAILOVER-EXEC-01
  TestCatch -> ROUTER-FAILOVER-CATCH-01
  TestLog   -> ROUTER-FAILOVER-LOG-01
  TestCost  -> ROUTER-FAILOVER-COST-01
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import litellm.exceptions
import pytest


pytestmark = pytest.mark.xfail(
    reason="Wave 0 scaffold — Plan 02 implements execute_with_fallback and removes this marker.",
    strict=True,
)


class TestExec:
    """ROUTER-FAILOVER-EXEC-01: execute_with_fallback iterates chain on retryable errors."""

    @pytest.mark.asyncio
    async def test_primary_succeeds_no_fallback(self):
        """Primary returns successfully -> chain_index=0, fallback_used=False."""
        from core.routing.failover_executor import execute_with_fallback
        # Plan 02: implement; assert chain_index == 0
        raise NotImplementedError

    @pytest.mark.asyncio
    async def test_primary_fails_secondary_succeeds(self):
        """Primary raises APIConnectionError -> secondary called -> chain_index=1, fallback_used=True."""
        raise NotImplementedError

    @pytest.mark.asyncio
    async def test_chain_exhausted(self):
        """All chain entries fail -> RouterChainExhaustedError with all attempts populated."""
        from core.routing.exceptions import RouterChainExhaustedError
        raise NotImplementedError


class TestCatch:
    """ROUTER-FAILOVER-CATCH-01: retryable vs non-retryable exception taxonomy."""

    @pytest.mark.asyncio
    async def test_non_retryable_authentication_error_reraises(self):
        """AuthenticationError on primary -> immediate re-raise, NO fallback attempt, attempts==1."""
        raise NotImplementedError

    @pytest.mark.asyncio
    async def test_context_window_exceeded_non_retryable(self):
        """ContextWindowExceededError (subclass of BadRequestError) re-raises — does NOT fallback."""
        raise NotImplementedError

    @pytest.mark.asyncio
    async def test_notfound_error_is_retryable(self):
        """NotFoundError on primary -> fallback DOES fire (NotFound is retryable per spec)."""
        raise NotImplementedError


class TestLog:
    """ROUTER-FAILOVER-LOG-01: reason chain extension with all 4 tag types."""

    @pytest.mark.asyncio
    async def test_reason_chain_tags_in_order(self):
        """Successful failover reason chain: [..., primary_failed:X, fallback_to:Y, completed:Y]."""
        raise NotImplementedError

    @pytest.mark.asyncio
    async def test_reason_chain_exhausted_tag(self):
        """Exhausted chain reason chain ends with 'chain_exhausted' tag."""
        raise NotImplementedError


class TestCost:
    """ROUTER-FAILOVER-COST-01: CostRecord captures actual model + chain_index + fallback_used."""

    @pytest.mark.asyncio
    async def test_cost_record_on_fallback(self):
        """After fallback to secondary: CostRecord.model == secondary, chain_index>0, fallback_used=True."""
        raise NotImplementedError

    @pytest.mark.asyncio
    async def test_cost_record_only_on_success_not_per_attempt(self):
        """One CostRecord per call (the success). Per-attempt failures go to stdout, NOT separate records."""
        raise NotImplementedError
