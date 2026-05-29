"""Envelope context variable — Phase 47.6 Plan 06 (Wave 3).

Provides a contextvar-based mechanism so lookup_capability calls during
agent reasoning can append CapabilityIntrospectionEvent rows to the active
AgentEnvelope without requiring explicit env passing.

The `envelope_context` context manager is the ONLY way to bind an envelope.
The tool dispatcher (tool_dispatcher.py) and lookup_capability both read
`current_envelope` to find the active envelope.

B2 invariant (CONTEXT.md decision #6c):
- lookup_capability reads current_envelope to APPEND to capability_introspection_log
- tool_dispatcher reads current_envelope to APPEND to capability_refusal_log (on invocation refusal)
- These are TWO SEPARATE lists — introspection never writes to refusal_log

Usage (agent dispatch):
    from core.agents.envelope_context import envelope_context

    with envelope_context(envelope):
        result = agent.run(...)
    # After context exits, envelope.capability_introspection_log populated

Usage (read-only, for CLI/dev safety):
    from core.agents.envelope_context import current_envelope

    env = current_envelope.get()  # returns None in CLI/dev context
    if env is not None:
        # Inside an active agent envelope; do introspection logging
        pass
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Optional

# The active agent envelope (set by envelope_context when dispatching agent
# turns). None when running outside an active agent envelope (dev, CLI, tests
# that don't wrap with envelope_context).
current_envelope: ContextVar[Optional[Any]] = ContextVar(
    "current_envelope", default=None
)

# The currently-dispatching Agent (set by agent.py process_tools() before
# dispatch_tool()). Phase 70.5 Plan 02 fix-up: the resolver instantiates
# Tool subclasses via object.__new__() to skip Tool.__init__, leaving
# self.agent unset and self.args = {}. Tools like CodeExecution crash on
# self.agent.handle_intervention(); ContractTool subclasses read self.args
# (not **kwargs) and forward empty args to the upstream VM. The resolver
# reads this contextvar to bind self.agent and self.args at call time so
# both code paths work without rewriting every tool to take kwargs.
current_agent: ContextVar[Optional[Any]] = ContextVar(
    "current_agent", default=None
)


@contextmanager
def envelope_context(envelope: Any) -> Iterator[None]:
    """Push envelope into contextvar; pop on exit (even on exception).

    This is the SOLE way to bind an envelope to the current execution context.
    Both lookup_capability and tool_dispatcher read current_envelope.get() to
    find the active envelope for log appending.

    Args:
        envelope: AgentEnvelope to bind for the duration of this context.

    Yields:
        None — the envelope is accessible via current_envelope.get() inside the block.

    Example:
        envelope = AgentEnvelope(...)
        with envelope_context(envelope):
            # lookup_capability calls here append to envelope.capability_introspection_log
            # tool_dispatcher refusals here append to envelope.capability_refusal_log
            result = agent.run(...)
        # Context exited — current_envelope.get() is None again (or previous value)
    """
    token = current_envelope.set(envelope)
    try:
        yield
    finally:
        current_envelope.reset(token)
