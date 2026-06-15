"""Bounded-concurrency guard for the Phase 85.1 dispatcher.

Wraps the per-task dispatch in a threading.Semaphore acquired before
work begins and released after the terminal status write. Sized via
VM107_TASK_DISPATCHER_MAX_CONCURRENT (upper bound: GovernanceMatrix
MAINTENANCE.max_active = 10 per RESEARCH.md Open Question #2).

Design rationale:
    WHY threading.BoundedSemaphore instead of asyncio.Semaphore:
        ``_dispatch_agent_sync`` is synchronous (uses ``asyncio.run`` internally).
        Wrapping in asyncio would require a nested event loop, which conflicts
        with the running loop inside ``asyncio.run``.  Threads give bounded
        concurrency without nested-loop complexity.

    WHY BoundedSemaphore (not Semaphore):
        BoundedSemaphore raises ValueError if release() is called more times
        than acquire(), preventing a class of bugs where a guard is released
        without being acquired (e.g., double-release on exception path).

    WHY a separate in_flight counter (not just the semaphore):
        threading.BoundedSemaphore has no public API to read the current
        in-flight count.  An explicit atomic counter allows the polling
        loop and tests to observe current concurrency without reconstructing
        it from semaphore internals.

Usage::

    guard = DispatcherConcurrencyGuard(max_concurrent=2)

    def dispatch_worker(task_id):
        with guard.slot(task_id):
            # do work here — semaphore is held for the duration
            run_task(task_id, ...)

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(dispatch_worker, t) for t in tasks]
        wait(futures)

    # in_flight == 0 after all futures resolve
"""
from __future__ import annotations

import contextlib
import logging
import threading
from typing import Iterator

logger = logging.getLogger(__name__)


class DispatcherConcurrencyGuard:
    """Thread-safe concurrency guard for the task dispatcher.

    Limits the number of concurrently executing tasks to ``max_concurrent``
    using a ``threading.BoundedSemaphore``.  An explicit ``in_flight`` counter
    (protected by a ``threading.Lock``) exposes current occupancy for tests
    and monitoring.

    Args:
        max_concurrent: Maximum number of tasks allowed to run simultaneously.
            Must be >= 1.  Raising after construction is not supported — create
            a new guard instead.

    Raises:
        ValueError: If ``max_concurrent < 1``.
    """

    def __init__(self, max_concurrent: int) -> None:
        if max_concurrent < 1:
            raise ValueError(
                f"max_concurrent must be >= 1; got {max_concurrent!r}. "
                f"Check VM107_TASK_DISPATCHER_MAX_CONCURRENT env var."
            )
        self._sem = threading.BoundedSemaphore(value=max_concurrent)
        self._max = max_concurrent
        self._in_flight = 0
        self._in_flight_lock = threading.Lock()

    @contextlib.contextmanager
    def slot(self, task_id: str) -> Iterator[None]:
        """Context manager that claims one concurrency slot.

        Blocks until a slot is available, increments the in-flight counter,
        yields control to the caller, then decrements the counter and
        releases the slot — even if the caller raises an exception.

        Args:
            task_id: Task identifier (used for structured log output only).

        Yields:
            None — use the ``with`` body to perform task work.
        """
        self._sem.acquire()
        with self._in_flight_lock:
            self._in_flight += 1
            current = self._in_flight

        try:
            logger.debug({
                "event": "dispatcher_slot_acquired",
                "task_id": task_id,
                "in_flight": current,
                "max": self._max,
            })
            yield
        finally:
            with self._in_flight_lock:
                self._in_flight -= 1
                released_at = self._in_flight
            self._sem.release()
            logger.debug({
                "event": "dispatcher_slot_released",
                "task_id": task_id,
                "in_flight": released_at,
                "max": self._max,
            })

    @property
    def in_flight(self) -> int:
        """Current number of in-flight (slot-acquired) tasks.

        Thread-safe: reads under ``_in_flight_lock``.
        """
        with self._in_flight_lock:
            return self._in_flight

    @property
    def max_concurrent(self) -> int:
        """Maximum concurrency cap this guard was configured with (read-only)."""
        return self._max
