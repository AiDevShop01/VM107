"""Phase 43.2 Plan 03 — codebase walker enforcing forbidden patterns absent outside allowlist.

Wave 0 status: xfail. Plan 03 implements the walker + allowlist + removes marker.

Covers STRUCTURED-IO-PHASE44-CONTRACT-01 (Phase 44 cannot bypass safe_parse / failover wrapper).
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.xfail(
    reason="Wave 0 scaffold — Plan 03 implements forbidden-pattern walker + removes marker.",
    strict=True,
)


class TestForbidden:
    """STRUCTURED-IO-PHASE44-CONTRACT-01: forbidden patterns absent outside allowlist."""

    def test_no_direct_parse_raw_in_codebase(self):
        """schema.parse_raw() forbidden everywhere (deprecated Pydantic v1)."""
        raise NotImplementedError

    def test_no_direct_parse_obj_in_codebase(self):
        """schema.parse_obj() forbidden everywhere (deprecated Pydantic v1)."""
        raise NotImplementedError

    def test_no_direct_model_validate_outside_allowlist(self):
        """schema.model_validate() forbidden outside allowlist (must go through safe_parse)."""
        raise NotImplementedError

    def test_no_direct_litellm_completion_outside_router(self):
        """litellm.completion() forbidden outside core/routing/ + models.py."""
        raise NotImplementedError

    def test_no_direct_unified_call_outside_failover_wrapper(self):
        """call_data['model'].unified_call() forbidden outside execute_with_fallback site."""
        raise NotImplementedError

    def test_no_direct_with_structured_output_outside_module(self):
        """llm.with_structured_output() forbidden outside core/agents/structured_output.py."""
        raise NotImplementedError
