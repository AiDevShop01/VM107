"""Phase 62.1 — BUG-16 unit test scaffold: ContractTool strips X-* scope headers.

BUG-16 root cause (tools/vm_contracts/base.py ~line 122):
    ``request = self._validate_request(self.args)``
  The scope-signing extension auto-injects ``X-Agent-Scope`` (and potentially
  other ``X-*`` keys) into ``self.args`` before validation.  Tools whose
  Request models use ``model_config = ConfigDict(extra="forbid")`` raise
  ``ValidationError: Extra inputs not permitted``.

Fix candidate (Option c per CONTEXT.md):
    Strip scope keys before contract validation in ``ContractTool._validate_request``.

Wave 1 (Plan 62.1-01) implements the strip-before-validate fix.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))

from tools.vm_contracts.base import ContractTool  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers — minimal ContractTool subclass with a forbid-extra model
# ---------------------------------------------------------------------------

def _make_contract_tool_with_args(args: dict) -> ContractTool:
    """Return a concrete ContractTool subclass instance with self.args = args.

    Wave 1 will replace this with a proper minimal subclass that declares a
    Request model with extra="forbid".  For now this is a duck-typed stub.
    """
    agent = MagicMock()
    agent.agent_id = "test_agent"
    # ContractTool is abstract — use a MagicMock spec
    tool = MagicMock(spec=ContractTool)
    tool.args = args
    return tool


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason="BUG-16 implementation pending in Phase 62.1 Plan 01 — X-Agent-Scope causes extra-inputs error today",
    strict=False,
    run=True,
)
def test_contract_tool_strips_x_agent_scope_from_args():
    """ContractTool._validate_request must strip ``X-Agent-Scope`` before Pydantic validation.

    Reproduces the ``ValidationError: Extra inputs not permitted`` failure seen
    when the scope dispatcher injects ``X-Agent-Scope`` into tool args for tools
    using ``model_config = ConfigDict(extra="forbid")``.
    """
    # Wave 1 will:
    # 1. Build a minimal ContractTool subclass with extra="forbid" Request model
    # 2. Inject X-Agent-Scope into args
    # 3. Assert _validate_request does NOT raise ValidationError
    # 4. Assert the returned request model does not have X-Agent-Scope field
    pytest.xfail("BUG-16 implementation pending in Phase 62.1 Plan 01")


@pytest.mark.xfail(
    reason="BUG-16 implementation pending in Phase 62.1 Plan 01 — any X-prefixed key triggers extra-inputs error",
    strict=False,
    run=True,
)
def test_contract_tool_strips_any_x_prefixed_key():
    """ContractTool._validate_request must strip ALL ``X-*`` prefixed keys, not just X-Agent-Scope.

    Future transport-layer injections (X-Correlation-ID, X-Request-ID, etc.)
    should be stripped by the same general rule to prevent the same class of
    ValidationError for any new header-backed injection.
    """
    pytest.xfail("BUG-16 implementation pending in Phase 62.1 Plan 01")


@pytest.mark.xfail(
    reason="BUG-16 implementation pending in Phase 62.1 Plan 01 — warning log not implemented yet",
    strict=False,
    run=True,
)
def test_contract_tool_logs_warning_when_stripping():
    """ContractTool must emit a warning log when X-* keys are stripped.

    The log provides an observability signal: if X-* injection patterns change
    upstream, the warning log makes it detectable without test failure.
    """
    pytest.xfail("BUG-16 implementation pending in Phase 62.1 Plan 01")


@pytest.mark.xfail(
    reason="BUG-16 implementation pending in Phase 62.1 Plan 01 — baseline: normal keys must still pass through",
    strict=True,
    run=True,
)
def test_contract_tool_does_not_strip_normal_keys():
    """ContractTool must NOT strip normal (non-X-prefixed) keys from args.

    This is a baseline regression lock: the X-* strip must be surgical.
    Normal tool parameters must reach _validate_request unchanged.
    """
    # Wave 1 will:
    # 1. Build a minimal ContractTool subclass accepting {execution_id: str}
    # 2. Pass {"execution_id": "abc123"} (no X-* keys)
    # 3. Assert validated model.execution_id == "abc123"
    pytest.xfail("BUG-16 baseline lock pending in Phase 62.1 Plan 01")
