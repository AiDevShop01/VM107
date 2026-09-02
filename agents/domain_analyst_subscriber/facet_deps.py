"""Phase 172 Plan 04 Task 1 — VM102-backed FacetDeps builder + reachability probe.

D-05 Option A (user-confirmed 2026-09-02): ``assemble()`` reads its REQUIRED
``domain_state`` facet from VM102 through a :class:`~core.evidence.assembler.FacetDeps`
whose ``domain_state_reader`` wraps ``fingpt_core.clients.VM102Client`` — NOT from
156's fetched ``Domain`` (whose composers read VM102, not the aggregate). Without a
wired ``FacetDeps`` every facet degrades to UNAVAILABLE (``state_version="unavailable"``)
and ``assess()`` abstains, so SC-1's "real claims" fails SILENTLY (RESEARCH Pitfall 1).

Honest-empty contract (D-02 / D-05):
* The reader NEVER raises into the composer — a transport failure (or a missing
  ``VM102_API_URL`` / ``VM102_SERVICE_JWT``) synthesizes a typed
  ``{"status":"unavailable", ...}`` envelope so the REQUIRED ``domain_state`` facet
  degrades honestly (mirrors ``evaluation_runner._fetch_primitives``'s
  ``not_available`` synthesis on transport failure).
* :func:`build_facet_deps` NEVER raises — the ``VM102Client`` is constructed LAZILY
  on first read so a subscriber host/container without VM102 env still gets a
  non-None reader that degrades honest-empty (rather than crashing at start-up).
* :func:`probe_vm102` performs ONE real ``get_domain_state`` and returns a bool; on
  an unreachable/unconfigured VM102 it logs a WARN naming the honest-empty fallback
  (Option B Domain-sourced composer / a follow-up) — it does NOT raise or brick.

G10 lock: the reader reaches DomainState ONLY via the typed
``VM102Client.get_domain_state`` seam. ``extra="forbid"`` on the frozen contracts is
untouched; no new env var is invented (the client reads ``VM102_API_URL`` /
``VM102_SERVICE_JWT`` exactly as elsewhere).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from core.evidence.assembler import FacetDeps

logger = logging.getLogger(__name__)

# Named in every honest-empty WARN so operators can trace a degraded pack back to
# the documented fallback (RESEARCH Priority Q3 Option B / Open Q1 follow-up).
_HONEST_EMPTY_FALLBACK = (
    "assemble() will yield an honest-empty pack (state_version='unavailable') and "
    "assess() will abstain; fix VM102 env (VM102_API_URL / VM102_SERVICE_JWT) + "
    "network, or land Option B (Domain-sourced composer) as a follow-up"
)


def _run_sync(make_coro: Callable[[], Any]) -> Any:
    """Drive an async coroutine to completion from a synchronous caller.

    ``EventBus.run`` dispatches ``subscriber.handle`` SYNCHRONOUSLY (there is no
    running event loop on that thread), so ``asyncio.run`` is the correct bridge.
    If a loop IS already running we execute in a dedicated worker thread with its
    own loop rather than ``asyncio.run`` (which would raise) or ``nest_asyncio``
    re-entry (which silently blocks the caller's loop — see
    ``project_vm107_nest_asyncio_masks_loop_blocking``). ``make_coro`` is a zero-arg
    factory so the coroutine is created inside whichever thread will await it (no
    "coroutine was never awaited" warning on the fallback path).
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(make_coro())

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(make_coro())).result()


class _VM102DomainStateReader:
    """Sync ``domain_state_reader`` adapter over the async ``VM102Client``.

    Exposes the typed seam the REQUIRED ``domain_state`` composer consumes
    (``core/evidence/facets/domain_state.py:88``):
    ``get_domain_state(country, domain_slug, *, knowledge_time=None, previous=False)``
    -> ``{"status","data","meta"}``. The client's response dict is passed THROUGH
    unchanged (its envelope already matches). On any transport/construction failure
    it synthesizes an honest ``{"status":"unavailable", ...}`` envelope — it NEVER
    raises out (D-02 no-brick).
    """

    def __init__(self, client_factory: Callable[[], Any]) -> None:
        self._client_factory = client_factory
        self._client: Any | None = None
        self._client_error: Exception | None = None

    def _ensure_client(self) -> Any | None:
        """Lazily construct the VM102Client; cache the failure so we warn once."""
        if self._client is not None:
            return self._client
        if self._client_error is not None:
            return None
        try:
            self._client = self._client_factory()
            return self._client
        except Exception as exc:  # noqa: BLE001 — missing env/config must degrade, not brick
            self._client_error = exc
            logger.warning(
                "facet_deps: VM102Client construction failed (%s: %s) — the reader "
                "will synthesize honest 'unavailable' envelopes. %s",
                type(exc).__name__, exc, _HONEST_EMPTY_FALLBACK,
            )
            return None

    @staticmethod
    def _unavailable(reason: str) -> dict:
        """A typed honest-empty envelope the domain_state composer degrades on."""
        return {"status": "unavailable", "data": {}, "meta": {"reason": reason}}

    def get_domain_state(
        self,
        country: str,
        domain_slug: str,
        *,
        knowledge_time: str | None = None,
        previous: bool = False,
    ) -> dict:
        client = self._ensure_client()
        if client is None:
            return self._unavailable(
                f"vm102-client-unconfigured: {type(self._client_error).__name__}: "
                f"{self._client_error}"
            )
        try:
            return _run_sync(
                lambda: client.get_domain_state(
                    country,
                    domain_slug,
                    knowledge_time=knowledge_time,
                    previous=previous,
                )
            )
        except Exception as exc:  # noqa: BLE001 — transport-fail => honest-empty, never raise
            logger.warning(
                "facet_deps: VM102 get_domain_state transport-fail country=%s "
                "slug=%s: %s: %s — synthesizing honest 'unavailable' envelope. %s",
                country, domain_slug, type(exc).__name__, exc, _HONEST_EMPTY_FALLBACK,
            )
            return self._unavailable(
                f"vm102-transport-fail: {type(exc).__name__}: {exc}"
            )


def build_facet_deps() -> FacetDeps:
    """Build a VM102-backed :class:`FacetDeps` (D-05 Option A).

    The REQUIRED ``domain_state_reader`` wraps ``VM102Client(RetryProfile.FAST_FAIL)``
    (constructed lazily on first read so this never raises on a host/container
    without VM102 env). The ENRICHMENT readers (``percentile_reader`` /
    ``evidence_reader`` / ``signal_reader`` / ...) stay ``None`` for the initial
    wiring — they degrade honest-deferred, which is acceptable (assemble() still
    yields a real ``state_version`` from the REQUIRED spine).
    """

    def _client_factory() -> Any:
        # Imported inside the factory so the module stays import-light and the
        # client's fail-fast env read only fires on first real use.
        from fingpt_core.clients import RetryProfile, VM102Client

        return VM102Client(profile=RetryProfile.FAST_FAIL)

    return FacetDeps(domain_state_reader=_VM102DomainStateReader(_client_factory))


def probe_vm102(
    deps: FacetDeps,
    *,
    country: str = "US",
    domain_slug: str = "growth",
) -> bool:
    """Perform ONE real ``get_domain_state`` to verify VM102 reachability (D-05).

    Returns ``True`` when VM102 answers with a usable envelope (``status`` in
    ``{"ok","degraded"}`` — a "degraded" read is a legitimate low-confidence RESULT,
    not an outage — see ``facets/domain_state.py``). Returns ``False`` (with a WARN
    naming the honest-empty fallback) on an ``unavailable``/error envelope, a missing
    reader, or any unexpected error. NEVER raises — the caller (``main()``) logs the
    result and proceeds either way (packs degrade honestly if unreachable).
    """
    reader = getattr(deps, "domain_state_reader", None)
    if reader is None:
        logger.warning(
            "probe_vm102: FacetDeps has no domain_state_reader — VM102 unwired. %s",
            _HONEST_EMPTY_FALLBACK,
        )
        return False

    try:
        envelope = (
            reader.get_domain_state(
                country, domain_slug, knowledge_time=None, previous=False
            )
            or {}
        )
    except Exception as exc:  # noqa: BLE001 — reader should never raise; probe must not either
        logger.warning(
            "probe_vm102: unexpected error %s: %s — treating VM102 as unreachable. %s",
            type(exc).__name__, exc, _HONEST_EMPTY_FALLBACK,
        )
        return False

    status = envelope.get("status")
    reachable = status in ("ok", "degraded")
    if reachable:
        logger.info(
            "probe_vm102: VM102 reachable (status=%r) — FacetDeps live; assemble() "
            "will yield real packs.",
            status,
        )
    else:
        reason = (envelope.get("meta") or {}).get("reason")
        logger.warning(
            "probe_vm102: VM102 read returned status=%r (reason=%r) — VM102 "
            "unreachable/unconfigured. %s",
            status, reason, _HONEST_EMPTY_FALLBACK,
        )
    return reachable
