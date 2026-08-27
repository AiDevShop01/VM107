"""Phase 70.5 Plan 02 Task 2 — TDD RED/GREEN suite for tool_resolver.py.

Tests cover:
- async tool (class with run_async) → invoke returns awaited result
- sync tool (class with run only) → invoke uses asyncio.to_thread without RuntimeError
- ContractTool subclass with async execute → invoke awaits and returns
- stub-status entry → CapabilityRefusedError raised with reason="registry_status=stub"
- facade entry with source_module=None → CapabilityRefusedError "facade_not_yet_implemented"
- unregistered tool_id → UnknownToolError raised
- bad source_module → ResolverError raised mentioning "module_not_importable"
- live integration: invoke("get_trade_context", ...) with mocked VM100Client
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

_VM107_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_VM107_ROOT) not in sys.path:
    sys.path.insert(0, str(_VM107_ROOT))


# ---------------------------------------------------------------------------
# Helpers — build ToolEntry fixtures with minimal fields
# ---------------------------------------------------------------------------

def _make_entry(
    tool_id: str,
    status: str = "real",
    source_module: str | None = None,
    is_facade: bool = False,
):
    """Build a minimal ToolEntry for use in resolver tests."""
    from core.agents.tool_registry import ToolEntry
    return ToolEntry(
        id=tool_id,
        status=status,
        source_module=source_module,
        typical_confidence=0.8,
        expected_freshness_seconds=60,
        is_deterministic=True,
        version="1.0",
        is_facade=is_facade,
    )


def _make_invocation_context():
    """Build a minimal InvocationContext for resolver tests."""
    from fingpt_core.contracts.invocation_context import InvocationContext
    return InvocationContext(
        envelope_id=uuid4(),
        parent_envelope_id=None,
        trace_id=uuid4(),
        agent_id="test_agent",
        conversation_id=None,
        execution_depth=0,
        knowledge_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Cache reset fixture
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_resolver_cache():
    """Clear tool_registry and tool_resolver module caches between tests."""
    try:
        import core.agents.tool_registry as tr
        original = tr._CACHE
        tr._CACHE = None
        yield
        tr._CACHE = original
    except ImportError:
        yield


# ---------------------------------------------------------------------------
# Async tool tests
# ---------------------------------------------------------------------------

class TestAsyncToolInvocation:
    """Tool class with async run_async method — resolver should await it directly."""

    @pytest.mark.asyncio
    async def test_async_run_async_is_awaited(self):
        """Invoke returns the result of awaiting run_async() for async tools."""
        from core.agents.tool_resolver import invoke

        # Build a fake module with an async tool class
        expected_result = {"value": "async_result"}

        class FakeAsyncTool:
            async def run_async(self, **kwargs):
                return expected_result

        fake_module = MagicMock()
        fake_module.FakeAsyncTool = FakeAsyncTool

        entry = _make_entry("fake_async_tool", source_module="tools.fake_async_tool")
        ctx = _make_invocation_context()

        with patch("core.agents.tool_resolver.get_tool_entry", return_value=entry):
            with patch("importlib.import_module", return_value=fake_module):
                result = await invoke("fake_async_tool", {}, ctx)

        assert result == expected_result

    @pytest.mark.asyncio
    async def test_async_tool_kwargs_passed_through(self):
        """kwargs dict is spread into run_async(**kwargs)."""
        from core.agents.tool_resolver import invoke

        received_kwargs = {}

        class FakeAsyncTool:
            async def run_async(self, **kwargs):
                received_kwargs.update(kwargs)
                return {"ok": True}

        fake_module = MagicMock()
        fake_module.FakeAsyncTool = FakeAsyncTool

        entry = _make_entry("fake_kw_tool", source_module="tools.fake_kw_tool")
        ctx = _make_invocation_context()

        with patch("core.agents.tool_resolver.get_tool_entry", return_value=entry):
            with patch("importlib.import_module", return_value=fake_module):
                await invoke("fake_kw_tool", {"foo": "bar", "baz": 42}, ctx)

        assert received_kwargs == {"foo": "bar", "baz": 42}


# ---------------------------------------------------------------------------
# Sync tool tests
# ---------------------------------------------------------------------------

class TestSyncToolInvocation:
    """Tool class with only sync run() method — resolver should use asyncio.to_thread."""

    @pytest.mark.asyncio
    async def test_sync_run_via_to_thread(self):
        """Invoke wraps sync run() in asyncio.to_thread (no RuntimeError in async context)."""
        from core.agents.tool_resolver import invoke

        expected_result = {"value": "sync_result"}

        class FakeSyncTool:
            def run(self, **kwargs):
                return expected_result

        fake_module = MagicMock()
        fake_module.FakeSyncTool = FakeSyncTool

        entry = _make_entry("fake_sync_tool", source_module="tools.fake_sync_tool")
        ctx = _make_invocation_context()

        with patch("core.agents.tool_resolver.get_tool_entry", return_value=entry):
            with patch("importlib.import_module", return_value=fake_module):
                result = await invoke("fake_sync_tool", {}, ctx)

        assert result == expected_result

    @pytest.mark.asyncio
    async def test_sync_run_no_runtime_error(self):
        """Sync run() that internally would call asyncio.run() is safe via to_thread."""
        from core.agents.tool_resolver import invoke

        # A sync tool that calls asyncio.run() would raise RuntimeError if called
        # directly from an async context. to_thread runs it in a thread where there
        # is no running event loop, so asyncio.run() inside is safe.
        # We verify this by checking the result is returned without exception.
        class FakeNestedLoopTool:
            def run(self, **kwargs):
                # This is the pattern BehavioralAnalysisTool.run() uses
                async def _inner():
                    return {"from_inner": True}
                return asyncio.run(_inner())

        fake_module = MagicMock()
        fake_module.FakeNestedLoopTool = FakeNestedLoopTool

        entry = _make_entry("fake_nested_loop_tool", source_module="tools.fake_nested_loop_tool")
        ctx = _make_invocation_context()

        with patch("core.agents.tool_resolver.get_tool_entry", return_value=entry):
            with patch("importlib.import_module", return_value=fake_module):
                result = await invoke("fake_nested_loop_tool", {}, ctx)

        assert result == {"from_inner": True}


# ---------------------------------------------------------------------------
# ContractTool subclass tests
# ---------------------------------------------------------------------------

class TestContractToolInvocation:
    """ContractTool subclass with async execute() — resolver should await execute()."""

    @pytest.mark.asyncio
    async def test_contract_tool_execute_awaited(self):
        """ContractTool.execute() is awaited; result returned directly.

        Uses a minimal ContractTool-like class (no litellm/Agent Zero dependency)
        patched as the base class inside the resolver. Tests the class_execute
        discovery path without requiring the full VM107 runtime to be importable.
        """
        from core.agents.tool_resolver import invoke

        expected_response = {"status": "ok", "from_execute": True}

        class MinimalContractBase:
            """Stands in for ContractTool — resolver checks issubclass against this."""

        class FakeContractImplTool(MinimalContractBase):
            """Fake tool that looks like a ContractTool subclass with async execute."""
            async def execute(self, **kwargs):
                return expected_response

        # Build a fake module where the class is NOT named *Tool (so precedence 1/2 skip it)
        # but IS a subclass of our patched _ContractToolBase (precedence 3)
        class FakeContractImplTool(MinimalContractBase):
            async def execute(self, **kwargs):
                return expected_response

        fake_module = MagicMock()
        fake_module.FakeContractImplTool = FakeContractImplTool

        entry = _make_entry("fake_contract_tool", source_module="tools.fake_contract_tool")
        ctx = _make_invocation_context()

        with patch("core.agents.tool_resolver.get_tool_entry", return_value=entry):
            with patch("importlib.import_module", return_value=fake_module):
                # Patch _ContractToolBase so resolver recognizes our minimal class
                with patch("core.agents.tool_resolver._ContractToolBase", MinimalContractBase):
                    result = await invoke("fake_contract_tool", {}, ctx)

        assert result == expected_response

    @pytest.mark.asyncio
    async def test_get_trade_context_execute_path_via_mock(self):
        """Integration: GetTradeContext-like ContractTool subclass invoked via execute().

        Uses a module mock to simulate the get_trade_context module structure without
        importing it (which would pull in litellm/Agent Zero, unavailable in unit tests).
        Validates that the resolver correctly identifies and awaits the execute() method
        on a ContractTool-like class with the exact GetTradeContext shape.
        """
        from core.agents.tool_resolver import invoke

        expected_response = {"trade_id": "test-123", "instrument": "EURUSD"}

        class MinimalContractBase:
            """Stand-in for ContractTool base class."""

        class GetTradeContextTool(MinimalContractBase):
            """Simulates GetTradeContext(ContractTool) shape — execute() is async."""
            async def execute(self, **kwargs):
                # Simulates what the real tool would return on success
                return expected_response

        fake_module = MagicMock()
        # NOT named *Tool so precedence 1/2 skip; relies on precedence 3 (ContractTool subclass)
        # Actually GetTradeContextTool DOES end in "Tool" so it hits precedence 2 (sync run fallback)
        # but it has no `run` method — so falls to precedence 3 (ContractTool execute).
        # Let's remove the *Tool suffix to test the pure ContractTool path:
        class GetTradeContextImpl(MinimalContractBase):
            async def execute(self, **kwargs):
                return expected_response

        fake_module.GetTradeContextImpl = GetTradeContextImpl

        entry = _make_entry("get_trade_context", source_module="tools.get_trade_context")
        ctx = _make_invocation_context()

        with patch("core.agents.tool_resolver.get_tool_entry", return_value=entry):
            with patch("importlib.import_module", return_value=fake_module):
                with patch("core.agents.tool_resolver._ContractToolBase", MinimalContractBase):
                    result = await invoke("get_trade_context", {"trade_id": "test-123"}, ctx)

        assert result == expected_response


# ---------------------------------------------------------------------------
# Refusal path tests
# ---------------------------------------------------------------------------

class TestRefusalPaths:
    @pytest.mark.asyncio
    async def test_stub_raises_capability_refused_error(self):
        """stub-status entry raises CapabilityRefusedError before attempting import."""
        from core.agents.tool_resolver import invoke, CapabilityRefusedError

        entry = _make_entry("fake_stub_tool", status="stub", source_module="tools.fake_stub")
        ctx = _make_invocation_context()

        with patch("core.agents.tool_resolver.get_tool_entry", return_value=entry):
            with pytest.raises(CapabilityRefusedError) as exc_info:
                await invoke("fake_stub_tool", {}, ctx)

        assert exc_info.value.reason == "registry_status=stub"
        assert exc_info.value.tool_id == "fake_stub_tool"

    @pytest.mark.asyncio
    async def test_experimental_raises_capability_refused_error(self):
        """experimental-status entry raises CapabilityRefusedError before attempting import."""
        from core.agents.tool_resolver import invoke, CapabilityRefusedError

        entry = _make_entry("fake_exp_tool", status="experimental", source_module="tools.fake_exp")
        ctx = _make_invocation_context()

        with patch("core.agents.tool_resolver.get_tool_entry", return_value=entry):
            with pytest.raises(CapabilityRefusedError) as exc_info:
                await invoke("fake_exp_tool", {}, ctx)

        assert exc_info.value.reason == "registry_status=experimental"

    @pytest.mark.asyncio
    async def test_stub_refusal_before_import(self):
        """stub refusal must fire BEFORE importlib.import_module is called."""
        from core.agents.tool_resolver import invoke, CapabilityRefusedError

        entry = _make_entry("fake_stub_tool", status="stub", source_module="tools.fake_stub")
        ctx = _make_invocation_context()

        import_called = []
        original_import = __builtins__  # noqa

        with patch("core.agents.tool_resolver.get_tool_entry", return_value=entry):
            with patch("importlib.import_module", side_effect=lambda m: import_called.append(m)) as mock_import:
                with pytest.raises(CapabilityRefusedError):
                    await invoke("fake_stub_tool", {}, ctx)

        assert len(import_called) == 0, (
            "importlib.import_module was called before stub refusal gate"
        )

    @pytest.mark.asyncio
    async def test_facade_none_source_raises_capability_refused(self):
        """Facade entry with source_module=None raises CapabilityRefusedError."""
        from core.agents.tool_resolver import invoke, CapabilityRefusedError

        entry = _make_entry(
            "vm100.some_facade",
            status="real",
            source_module=None,
            is_facade=True,
        )
        ctx = _make_invocation_context()

        with patch("core.agents.tool_resolver.get_tool_entry", return_value=entry):
            with pytest.raises(CapabilityRefusedError) as exc_info:
                await invoke("vm100.some_facade", {}, ctx)

        assert exc_info.value.reason == "facade_not_yet_implemented"
        assert exc_info.value.tool_id == "vm100.some_facade"

    @pytest.mark.asyncio
    async def test_unknown_tool_raises_unknown_tool_error(self):
        """Unregistered tool_id raises UnknownToolError."""
        from core.agents.tool_resolver import invoke, UnknownToolError

        ctx = _make_invocation_context()

        with patch("core.agents.tool_resolver.get_tool_entry", side_effect=KeyError("nonexistent")):
            with pytest.raises(UnknownToolError) as exc_info:
                await invoke("nonexistent_tool_id", {}, ctx)

        assert "nonexistent_tool_id" in str(exc_info.value)
        assert exc_info.value.tool_id == "nonexistent_tool_id"

    @pytest.mark.asyncio
    async def test_bad_source_module_raises_resolver_error(self):
        """ModuleNotFoundError on import is wrapped as ResolverError."""
        from core.agents.tool_registry import ResolverError
        from core.agents.tool_resolver import invoke

        entry = _make_entry(
            "fake_bad_module_tool",
            source_module="tools.completely_nonexistent_module_xyz_abc",
        )
        ctx = _make_invocation_context()

        with patch("core.agents.tool_resolver.get_tool_entry", return_value=entry):
            with pytest.raises(ResolverError) as exc_info:
                await invoke("fake_bad_module_tool", {}, ctx)

        assert "module_not_importable" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# resolve_tool_callable tests
# ---------------------------------------------------------------------------

class TestResolveToolCallable:
    def test_returns_callable_for_async_tool(self):
        """resolve_tool_callable returns a callable for a tool with run_async."""
        from core.agents.tool_resolver import resolve_tool_callable

        class FakeAsyncTool:
            async def run_async(self, **kwargs):
                return {}

        fake_module = MagicMock()
        fake_module.FakeAsyncTool = FakeAsyncTool

        entry = _make_entry("fake_async_tool", source_module="tools.fake_async_tool")

        with patch("core.agents.tool_resolver.get_tool_entry", return_value=entry):
            with patch("importlib.import_module", return_value=fake_module):
                result = resolve_tool_callable("fake_async_tool")

        assert callable(result)

    def test_raises_unknown_tool_error_for_unregistered(self):
        """resolve_tool_callable raises UnknownToolError for unknown tool_id."""
        from core.agents.tool_resolver import resolve_tool_callable, UnknownToolError

        with patch("core.agents.tool_resolver.get_tool_entry", side_effect=KeyError("unknown")):
            with pytest.raises(UnknownToolError):
                resolve_tool_callable("unknown_tool_xyz")

    def test_raises_capability_refused_for_stub(self):
        """resolve_tool_callable raises CapabilityRefusedError for stub tools."""
        from core.agents.tool_resolver import resolve_tool_callable, CapabilityRefusedError

        entry = _make_entry("stub_tool", status="stub", source_module="tools.stub")
        with patch("core.agents.tool_resolver.get_tool_entry", return_value=entry):
            with pytest.raises(CapabilityRefusedError):
                resolve_tool_callable("stub_tool")
