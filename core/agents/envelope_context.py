"""Envelope context variable — minimal shim for Wave 1 (Phase 47.6 Plan 03).

Wave 3 (Plan 06) fills in the actual envelope binding and introspection-log
writer. For Wave 1 we only need the contextvar to import without crashing in
dev/CLI contexts where no envelope is active.

Usage:
    from core.agents.envelope_context import current_envelope

    env = current_envelope.get()  # returns None in CLI/dev context
    if env is not None:
        # Inside an active agent envelope; do introspection logging
        pass
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Optional

# The active agent envelope (set by the envelope runner when dispatching agent
# turns). None when running outside an active agent envelope (dev, CLI, tests).
#
# Wave 3 Plan 06: bind this contextvar in the envelope runner's execution path
# and implement the actual CapabilityIntrospectionEvent append.
current_envelope: ContextVar[Optional[Any]] = ContextVar(
    "current_envelope", default=None
)
