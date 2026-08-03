"""Phase 132 Plan 01 — SC-1 RED unit test.

Asserts that a bounded DeferredTask.result_sync(timeout) raises a *typed*
`InitTimeout` (subclass of TimeoutError) on expiry, rather than the builtin
TimeoutError. This is the "abort a hung deferred init instead of blocking the
main boot thread forever" contract (run_ui.py:83 wedge).

RED until Wave 1 (132-02) adds `class InitTimeout(TimeoutError)` to helpers/defer.py
and raises it from result_sync/result on expiry. The `InitTimeout` symbol is imported
LAZILY inside the test body so pytest --collect-only succeeds while the assertion is RED.
"""
from __future__ import annotations

import asyncio

import pytest


@pytest.mark.quick
def test_result_sync_raises_init_timeout_on_expiry():
    """A never-completing deferred init, bounded by result_sync(timeout), raises InitTimeout."""
    # Lazy imports so collection succeeds before the Wave 1 symbol lands.
    from helpers.defer import DeferredTask
    from helpers.defer import InitTimeout  # RED: does not exist until 132-02

    # InitTimeout must be a TimeoutError subclass (Liskov-safe for existing
    # `except TimeoutError` callers).
    assert issubclass(InitTimeout, TimeoutError)

    async def _hang():
        await asyncio.sleep(999)

    task = DeferredTask().start_task(_hang)
    try:
        with pytest.raises(InitTimeout):
            # Bounded wait — must raise fast (well within the 60s pytest timeout).
            task.result_sync(timeout=0.2)
    finally:
        # Never leave the background coroutine parked.
        task.kill()
