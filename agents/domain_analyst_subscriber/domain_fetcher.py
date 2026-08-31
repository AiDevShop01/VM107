"""Phase 156 (AZE-02 / blocker B1) — DomainSnapshotFetcher.

The production ``domain_fetcher`` the :class:`DomainAnalystSubscriber` injects
so the 12 domain analysts fire on real, validated ``Domain`` data on every
``MACRO_RELEASE`` (today ``main()`` passes ``domain_fetcher=None`` → every
release is logged-and-dropped).

Read path (D-01): reuse the blessed ``get_domain_health`` contract — a
**synchronous** ``httpx`` GET to the VM100 self-endpoint
``/api/macro-situation/domain/{slug}?country={event.country}`` with an
``Authorization: Bearer {VM107_SERVICE_JWT}`` header. Never an in-process store
read. The subscriber ``handle()`` is synchronous, so this mirrors the shipped
sync JWT client ``services/macro_calendar_client.py`` — but DEVIATES from its
blanket ``except -> []`` swallow: D-02 requires distinct, honest branches.

Error branch map (D-02):
  * ``slug not in DOMAIN_SLUGS``    → ``log.warning`` + ``None``, NO HTTP call.
  * HTTP ``404`` (known slug)       → ``log.info`` + ``None`` (snapshot not
    ready yet → retry-friendly; the subscriber leaves the idempotency/debounce
    slot unmarked so the release is re-processed when the snapshot lands).
  * ``400 / 401 / 5xx``             → ``raise_for_status()`` (loud; routes
    through the subscriber ``except`` → no key-mark).
  * net / timeout (``httpx.HTTPError``) → re-raised as a distinct
    ``RuntimeError`` (transient → no key-mark).
  * ``200``                         → ``Domain.model_validate(resp.json())``
    INSIDE the fetcher so a ``ValidationError`` surfaces loudly (Pitfall 1),
    never swallowed as a "retryable analyst failure".

Env (fail-fast at import — CLAUDE.md env-driven-config lock, no defaults for
required vars; present in the subscriber container via ``env_file: .env.local``):
  VM100_API_URL          — base URL of VM100 (e.g. http://host.docker.internal:8000)
  VM107_SERVICE_JWT      — HS256 bearer for the VM100 JWTAuth gate (NEVER logged)
  DOMAIN_FETCH_TIMEOUT_SEC — optional, default 5 seconds

Guards (never break these):
  * NEVER re-mint ``knowledge_time`` — the subscriber threads the event's as-of
    immutably; the fetcher must not read a wall clock (Constitution 18).
  * NEVER compute domain health — the fetcher only fetches (the never-recompute
    static guard scans ``agents/{slug}_domain_analyst/agent.py`` only, but keep
    this module compute-free regardless).
  * NEVER log the JWT value.
"""

from __future__ import annotations

import logging
import os

import httpx

from agents.domain_analyst_subscriber.subscriber import DOMAIN_SLUGS
from contracts.economic_intelligence.domain import Domain
from contracts.economic_intelligence.events import EconomicEvent

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fail-fast module-level env validation (CLAUDE.md env-driven-config lock).
# No os.getenv("X", "default") for required vars — fail at import if missing.
# ---------------------------------------------------------------------------
_BASE_URL: str = os.environ["VM100_API_URL"]
_JWT: str = os.environ["VM107_SERVICE_JWT"]
_TIMEOUT: float = float(os.environ.get("DOMAIN_FETCH_TIMEOUT_SEC", "5"))


class DomainSnapshotFetcher:
    """Sync VM107 → VM100 domain-snapshot client returning a validated ``Domain``.

    Callable ``(slug, event) -> Domain | None`` — injected at
    ``DomainAnalystSubscriber`` construction and delegated to by
    ``_fetch_domain``.

    Constructor accepts explicit overrides so tests can bypass the module-level
    env constants without reloading the module (mirrors
    ``MacroCalendarHTTPClient``).
    """

    def __init__(
        self,
        base_url: str = _BASE_URL,
        jwt: str = _JWT,
        timeout_sec: float = _TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._jwt = jwt
        self._timeout = timeout_sec

    def __call__(self, slug: str, event: EconomicEvent) -> Domain | None:
        # D-02 unknown-slug drop — belt-and-braces (the subscriber already
        # filters non-canonical slugs before calling the fetcher). No HTTP call.
        if slug not in DOMAIN_SLUGS:
            log.warning(
                "domain_fetcher: unknown slug %r — dropping (not one of the "
                "canonical 12; no HTTP call made)",
                slug,
            )
            return None

        url = f"{self._base_url}/api/macro-situation/domain/{slug}"
        try:
            resp = httpx.get(
                url,
                params={"country": event.country},
                headers={"Authorization": f"Bearer {self._jwt}"},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            # Network / timeout — transient. Re-raise as a distinct error so the
            # subscriber's except path handles it (which does NOT mark the key).
            raise RuntimeError(
                f"domain_fetcher transient error slug={slug}: {type(exc).__name__}"
            ) from exc

        if resp.status_code == 404:
            # Known-canonical slug (filtered above) ⇒ 404 means "snapshot not
            # ready yet" ⇒ return None; the subscriber leaves the slot unmarked
            # so the release is re-processed when the snapshot lands (D-02).
            log.info(
                "domain_fetcher: snapshot not ready slug=%s country=%s (404) "
                "— retry-friendly (idempotency/debounce NOT marked)",
                slug,
                event.country,
            )
            return None

        # 400 / 401 / 5xx — loud, routes through the subscriber except → no mark.
        resp.raise_for_status()

        # 200 — validate at the boundary. A ValidationError surfaces loudly
        # (Pitfall 1) rather than being swallowed as a "retryable analyst
        # failure"; the frozen + extra="forbid" Domain enforces exact shape.
        return Domain.model_validate(resp.json())
