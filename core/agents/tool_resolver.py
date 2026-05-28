"""Phase 70.5 Plan 02 — runtime tool callable resolution.

Decision 15 lock: resolves tool_id → bound callable using the typed ToolEntry from
tool_registry.py. Harmonizes sync (.run()), async (.run_async() / .execute()) tool
shapes behind a single `async def invoke(...)` API the dispatcher (Plan 03) consumes.

Discovery precedence inside the imported module:
  1. Class with `async def run_async` method → await directly (preferred)
  2. Class with sync `def run` method → asyncio.to_thread (safe for tools that
     call asyncio.run() internally, e.g. BehavioralAnalysisTool.run — RESEARCH Pitfall 7)
  3. Class subclass of ContractTool (from tools.vm_contracts.base) with `async def execute`
     → await execute(**kwargs) (GetTradeContext pattern)
  4. Top-level `async def run_async` function → await directly
  5. Top-level sync `def run` function → asyncio.to_thread

Class discovery heuristic (inside the imported module):
  - Find the first class whose name ends with "Tool" (e.g. BehavioralAnalysisTool,
    GetTradeContext, ExecutionQualityTool) — case-sensitive suffix match.
  - If no *Tool class found, check for ContractTool subclasses.
  - If still not found, check for top-level run / run_async functions.
  - Raises ResolverError if no callable found after exhausting all options.

Async handling rationale (RESEARCH Pitfall 7):
  - BehavioralAnalysisTool.run() calls asyncio.run() internally, which raises
    RuntimeError("This event loop is already running") when called from within
    an async context (the dispatcher is async). The resolver MUST call run_async()
    when present and only fall back to asyncio.to_thread() for genuinely sync tools.

Public API:
    UnknownToolError         — raised when tool_id is not registered
    CapabilityRefusedError   — raised when a stub/experimental or unimplemented facade tool is invoked
    resolve_tool_callable()  — synchronous callable discovery (no invocation)
    invoke()                 — single uniform async invocation API for the dispatcher

Internal seam:
    _ContractToolBase        — the ContractTool base class, exported at module level so
                               tests can patch it (patch("core.agents.tool_resolver._ContractToolBase"))
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
from typing import Any, Callable

from fingpt_core.contracts.invocation_context import InvocationContext

from core.agents.tool_registry import ResolverError, ToolEntry, get_tool_entry


class UnknownToolError(Exception):
    """Raised when tool_id is not registered in the capability registry.

    Mirrors tool_dispatcher.UnknownToolError but raised at the resolver layer
    (before the dispatcher layer) to short-circuit before any invocation logic.
    """
    def __init__(self, tool_id: str) -> None:
        super().__init__(f"Unknown tool: {tool_id!r} — not registered in capability registry")
        self.tool_id = tool_id


class CapabilityRefusedError(Exception):
    """Raised when a registry stub/experimental or unimplemented facade tool is invoked.

    The dispatcher (Plan 03) catches this exception and builds the structured refusal
    envelope. The resolver does NOT build envelopes — it only raises the exception.

    Attributes:
        tool_id: The capability id that was refused.
        reason:  Machine-readable reason string. Values:
                 - "registry_status=stub"             (Phase 47.6 LD-6c)
                 - "registry_status=experimental"     (Phase 47.6 LD-6c)
                 - "facade_not_yet_implemented"        (Plan 07 proxy not yet shipped)
    """
    def __init__(self, tool_id: str, reason: str) -> None:
        super().__init__(f"Capability refused: {tool_id!r} — {reason}")
        self.tool_id = tool_id
        self.reason = reason


def _load_contract_tool_base():
    """Lazy import of ContractTool base class.

    Lazy to avoid importing the entire tools hierarchy at module load time.
    Returns None if tools.vm_contracts.base is not importable (e.g. in unit test
    environments where Agent Zero's litellm dependency is not present).
    """
    try:
        from tools.vm_contracts.base import ContractTool
        return ContractTool
    except (ImportError, Exception):
        return None


# Module-level reference to ContractTool base class (patched in tests).
# Initialized lazily on first use.
_ContractToolBase: type | None = None


def _get_contract_tool_base() -> type | None:
    """Return the ContractTool base class, loading lazily if needed."""
    global _ContractToolBase
    if _ContractToolBase is None:
        _ContractToolBase = _load_contract_tool_base()
    return _ContractToolBase


def _discover_callable(module: Any, tool_id: str) -> tuple[Any, str]:
    """Discover the callable inside an imported module.

    Returns a (callable_or_instance, discovery_path) tuple where discovery_path
    is a human-readable string documenting which branch was taken.

    Discovery precedence (see module docstring):
    1. Class ending in "Tool" with run_async → "class_run_async"
    2. Class ending in "Tool" with sync run  → "class_run_sync"
    3. ContractTool subclass with async execute → "class_execute"
    4. Top-level async run_async function → "fn_run_async"
    5. Top-level sync run function → "fn_run_sync"

    Raises:
        ResolverError: If no callable pattern found.
    """
    contract_tool_base = _get_contract_tool_base()

    # Precedence 1 & 2: Class with name ending in "Tool"
    for name, obj in inspect.getmembers(module, inspect.isclass):
        if name.endswith("Tool"):
            # Precedence 1: async run_async
            if hasattr(obj, "run_async") and asyncio.iscoroutinefunction(getattr(obj, "run_async")):
                return (obj(), "class_run_async")
            # Precedence 2: sync run
            if hasattr(obj, "run") and callable(getattr(obj, "run")):
                return (obj(), "class_run_sync")

    # Precedence 3: ContractTool subclass with async execute
    if contract_tool_base is not None:
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                obj is not contract_tool_base
                and issubclass(obj, contract_tool_base)  # type: ignore[arg-type]
                and hasattr(obj, "execute")
                and asyncio.iscoroutinefunction(getattr(obj, "execute"))
            ):
                # ContractTool subclasses use the Tool base which normally needs
                # agent/args — we create a bare instance via object.__new__ to
                # avoid the Tool.__init__ dependency at discovery time.
                # The dispatcher owns full initialization; at discovery time we
                # just need to confirm the class exists and has execute().
                try:
                    instance = object.__new__(obj)
                    # Set minimal attributes ContractTool.execute needs
                    instance.args = {}
                    instance.name = name
                    return (instance, "class_execute")
                except Exception:
                    # If we can't instantiate, fall through to next precedence
                    pass

    # Also check any class with "execute" as async (more permissive fallback for test mocks)
    for name, obj in inspect.getmembers(module, inspect.isclass):
        if hasattr(obj, "execute") and asyncio.iscoroutinefunction(getattr(obj, "execute")):
            try:
                instance = object.__new__(obj)
                instance.args = {}
                instance.name = name
                return (instance, "class_execute")
            except Exception:
                pass

    # Precedence 4: top-level async run_async function
    run_async_fn = getattr(module, "run_async", None)
    if run_async_fn is not None and asyncio.iscoroutinefunction(run_async_fn):
        return (run_async_fn, "fn_run_async")

    # Precedence 5: top-level sync run function
    run_fn = getattr(module, "run", None)
    if run_fn is not None and callable(run_fn):
        return (run_fn, "fn_run_sync")

    raise ResolverError(
        f"No callable found in module for tool {tool_id!r}. "
        "Expected a class ending in 'Tool' with run_async/run, "
        "a ContractTool subclass with execute, "
        "or top-level run_async/run functions."
    )


async def _call_instance(instance: Any, discovery_path: str, kwargs: dict) -> Any:
    """Invoke the discovered callable with the given kwargs.

    Applies the correct async/sync/execute invocation pattern based on discovery_path.
    """
    if discovery_path == "class_run_async":
        return await instance.run_async(**kwargs)
    elif discovery_path == "class_run_sync":
        # Use asyncio.to_thread to avoid RuntimeError when the tool calls asyncio.run()
        return await asyncio.to_thread(instance.run, **kwargs)
    elif discovery_path == "class_execute":
        return await instance.execute(**kwargs)
    elif discovery_path == "fn_run_async":
        return await instance(**kwargs)
    elif discovery_path == "fn_run_sync":
        return await asyncio.to_thread(instance, **kwargs)
    else:
        raise ResolverError(f"Unknown discovery path: {discovery_path!r}")


def resolve_tool_callable(tool_id: str) -> Callable[..., Any]:
    """Return the bound callable for tool_id.

    Synchronous discovery only — does not invoke the callable.
    Performs full refusal gate (stub/experimental) and module import.

    The returned callable is the bound method or function that invoke() would call:
    - For run_async tools: instance.run_async (bound method)
    - For sync run tools: instance.run (bound method)
    - For execute tools: instance.execute (bound method)
    - For top-level functions: the function itself

    Args:
        tool_id: The capability id to resolve.

    Returns:
        The bound callable (bound method or function).

    Raises:
        UnknownToolError:       If tool_id is not registered.
        CapabilityRefusedError: If the tool is stub/experimental or a facade without implementation.
        ResolverError:          If the module cannot be imported or no callable found.
    """
    try:
        entry = get_tool_entry(tool_id)
    except KeyError as exc:
        raise UnknownToolError(tool_id) from exc

    if entry.status in ("stub", "experimental"):
        raise CapabilityRefusedError(tool_id, f"registry_status={entry.status}")

    if entry.source_module is None:
        raise CapabilityRefusedError(tool_id, "facade_not_yet_implemented")

    try:
        module = importlib.import_module(entry.source_module)
    except ModuleNotFoundError as exc:
        raise ResolverError(
            f"module_not_importable: {entry.source_module!r} for tool {tool_id!r}"
        ) from exc

    instance, discovery_path = _discover_callable(module, tool_id)

    # Return the specific bound callable (method or function)
    if discovery_path == "class_run_async":
        return instance.run_async
    elif discovery_path == "class_run_sync":
        return instance.run
    elif discovery_path == "class_execute":
        return instance.execute
    elif discovery_path in ("fn_run_async", "fn_run_sync"):
        return instance  # top-level function, already callable
    else:
        raise ResolverError(f"Unknown discovery path: {discovery_path!r}")


async def invoke(tool_id: str, kwargs: dict, ctx: InvocationContext) -> Any:
    """Single uniform async invocation API consumed by the dispatcher (Plan 03).

    Returns the typed payload the tool produced (NOT a ToolResultEnvelope — the
    dispatcher wraps the result in an envelope after this call returns).

    The `ctx` InvocationContext is accepted but not yet actively used inside the
    resolver (Plan 03 dispatcher constructs and threads it through). The signature
    accepts it now so Plan 03 can call without an API change.

    Refusal short-circuit order:
      1. UnknownToolError if not in registry (KeyError → UnknownToolError)
      2. CapabilityRefusedError if status is stub/experimental (BEFORE import)
      3. CapabilityRefusedError if facade with source_module=None (BEFORE import)
      4. ResolverError if module fails to import (ModuleNotFoundError → ResolverError)
      5. ResolverError if no callable found in the module

    Args:
        tool_id: The capability id to invoke (must match registry id exactly).
        kwargs:  Tool keyword arguments spread into the callable as **kwargs.
        ctx:     InvocationContext for lineage threading (unused in Plan 02; Plan 03 uses it).

    Returns:
        The result returned by the tool (typed payload, Response, or raw dict).

    Raises:
        UnknownToolError:       tool_id not registered
        CapabilityRefusedError: stub/experimental or facade-not-yet-implemented
        ResolverError:          module import failed or no callable found
    """
    # Step 1: Resolve the entry (raises UnknownToolError if not registered)
    try:
        entry = get_tool_entry(tool_id)
    except KeyError as exc:
        raise UnknownToolError(tool_id) from exc

    # Step 2: Refusal gate — stub/experimental BEFORE any import (LD-6c)
    if entry.status in ("stub", "experimental"):
        raise CapabilityRefusedError(tool_id, f"registry_status={entry.status}")

    # Step 3: Facade without implementation gate — BEFORE import
    if entry.source_module is None:
        raise CapabilityRefusedError(tool_id, "facade_not_yet_implemented")

    # Step 4: Lazy module import (avoids importing 37 modules at VM107 startup)
    try:
        module = importlib.import_module(entry.source_module)
    except ModuleNotFoundError as exc:
        raise ResolverError(
            f"module_not_importable: {entry.source_module!r} for tool {tool_id!r}"
        ) from exc

    # Step 5: Discover callable and invoke
    instance, discovery_path = _discover_callable(module, tool_id)
    return await _call_instance(instance, discovery_path, kwargs)
