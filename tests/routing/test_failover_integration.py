"""Phase 43.2 Plan 04 — execute_with_fallback integration test.

Real LiteLLM call: primary set to http://127.0.0.1:1 (deterministic ConnectionError),
secondary set to deepseek/deepseek-v4-flash (real call). Tests the full path:
hook -> router -> wrapper -> LiteLLM -> exception -> fallback -> success.

Gated on DEEPSEEK_API_KEY env var (skip if absent).

Wave 0 status: xfail. Plan 04 implements + removes marker.
"""

from __future__ import annotations

import os

import pytest


pytestmark = [
    pytest.mark.integration,
    pytest.mark.xfail(
        reason="Wave 0 scaffold — Plan 04 implements integration test + canary asset.",
        strict=True,
    ),
]


class TestE2EUnreachable:
    """ROUTER-FAILOVER-VERIFY-01: real failover with unreachable primary."""

    @pytest.mark.skipif(
        not os.environ.get("DEEPSEEK_API_KEY"),
        reason="Requires DEEPSEEK_API_KEY env var for real fallback model call",
    )
    @pytest.mark.asyncio
    async def test_unreachable_primary_real_fallover(self):
        """Configure primary=http://127.0.0.1:1, secondary=deepseek/deepseek-v4-flash.
        Real LiteLLM acompletion call -> real ConnectionError -> real failover.
        Asserts ALL FOUR layers:
          1. Execution: secondary actually invoked (response != error)
          2. Reason chain: ['primary_failed:APIConnectionError', 'fallback_to:deepseek-v4-flash', 'completed:deepseek-v4-flash']
          3. CostRecord: model=deepseek/deepseek-v4-flash, chain_index=1, fallback_used=True
          4. Stdout logs: 'model_failure' and 'model_success' events present
        """
        raise NotImplementedError
