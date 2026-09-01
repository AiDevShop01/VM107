"""Phase 155 (D-01 / D-01a) — PillarSnapshotFetcher.

Reuse-first pillar source for the macro-ask fan-out executor. Instead of recomputing or
reading an in-process store, this fetcher performs a **synchronous** ``httpx`` GET against
the blessed VM100 dashboard contract
``GET /api/macro-situation/dashboard?country={country}`` with an
``Authorization: Bearer {VM107_SERVICE_JWT}`` header, then adapts the nested pillar section
(``sections.pillars.pillars.<PillarName>``) into the frozen ``Pillar`` contract.

Structural adapter, NOT a field-level one (D-01a / RESEARCH Validation 1): the ``Pillar``
contract is byte-identical VM100↔VM107 (unlike Phase 156's ``Domain``, which needed a
presentational-field strip). So there is NO ``.pop()`` here — any genuinely extra field
must raise loudly at ``Pillar.model_validate`` (fail-fast, T-155-02), never be silently
stripped.

Error branch map (mirrors DomainSnapshotFetcher):
  * HTTP ``404`` / ``503``            → ``None`` (snapshot "not ready yet" — honest degrade).
  * present-but-``null`` per-pillar   → ``None`` (degraded basket, never a fabricated Pillar).
  * pillars section missing/absent    → ``None`` (honest degrade).
  * other ``4xx`` / ``5xx``           → ``raise_for_status()`` (loud; the executor must see it).
  * net / timeout (``httpx.HTTPError``) → re-raised as a distinct ``RuntimeError`` (transient).
  * ``200`` with a pillar dump        → ``Pillar.model_validate(pdict)`` at the boundary.

Env (fail-fast at import — CLAUDE.md env-driven-config lock, NO defaults for required vars):
  VM100_API_URL             — base URL of VM100 (e.g. http://host.docker.internal:8000)
  VM107_SERVICE_JWT         — HS256 bearer for the VM100 JWTAuth gate (NEVER logged, T-155-01)
  PILLAR_FETCH_TIMEOUT_SEC  — optional, default 5 seconds (T-155-08 bounded wait)

Scope note (RESEARCH Open Q1 / Pitfall 6): this fetcher sources only the 4 pillar names
(Growth / Inflation / Liquidity / RiskAppetite). A non-pillar routed id is handled by the
executor's honest-degrade path (155-03), not here.
"""

from __future__ import annotations

import logging
import os

import httpx

from contracts.economic_intelligence.pillars import Pillar

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fail-fast module-level env validation (CLAUDE.md env-driven-config lock).
# No os.getenv("X", "default") for required vars — fail at import if missing.
# ---------------------------------------------------------------------------
_BASE_URL: str = os.environ["VM100_API_URL"]
_JWT: str = os.environ["VM107_SERVICE_JWT"]
_TIMEOUT: float = float(os.environ.get("PILLAR_FETCH_TIMEOUT_SEC", "5"))


class PillarSnapshotFetcher:
    """Sync VM107 → VM100 dashboard client returning a validated ``Pillar`` (or ``None``).

    ``get(pillar_name, country="US") -> Pillar | None`` — the executor injects this and
    resolves each routed specialist id to a ``PillarName`` before calling.

    Constructor accepts explicit overrides so tests bypass the module-level env constants
    without reloading the module (mirrors ``DomainSnapshotFetcher`` / ``MacroCalendarHTTPClient``).
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
        # Reusable sync client. Tests monkeypatch ``_client`` with a MockTransport client
        # AFTER construction, so no real connection is opened during the unit suite.
        self._client = httpx.Client(timeout=self._timeout)

    def get(self, pillar_name: str, country: str = "US") -> Pillar | None:
        url = f"{self._base_url}/api/macro-situation/dashboard"
        try:
            resp = self._client.get(
                url,
                params={"country": country},
                headers={"Authorization": f"Bearer {self._jwt}"},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            # Network / timeout — transient. Re-raise as a distinct error (JWT-free message)
            # so the executor's honest-degrade path handles it. NEVER embed the bearer.
            raise RuntimeError(
                f"pillar_fetcher transient error pillar={pillar_name} "
                f"country={country}: {type(exc).__name__}"
            ) from exc

        # 404 / 503 — snapshot not ready yet ⇒ honest degrade (None), retry-friendly.
        if resp.status_code in (404, 503):
            log.info(
                "pillar_fetcher: snapshot not ready pillar=%s country=%s (%s) — degrade to None",
                pillar_name,
                country,
                resp.status_code,
            )
            return None

        # Other 4xx / 5xx — loud (the executor must see the fault, not a silent None).
        resp.raise_for_status()

        # 200 — navigate sections.pillars.pillars.<PillarName>. A present-but-null value
        # (or an absent/UNAVAILABLE pillars section) degrades honestly to None.
        payload = resp.json()
        sections = payload.get("sections") or {}
        pillars_section = sections.get("pillars") or {}
        pillars_map = pillars_section.get("pillars") or {}
        pdict = pillars_map.get(pillar_name)
        if pdict is None:
            log.info(
                "pillar_fetcher: pillar=%s absent/null in dashboard (country=%s) — degrade to None",
                pillar_name,
                country,
            )
            return None

        # Boundary validate — NO .pop() of any key (D-01a: byte-identical contract; a
        # genuinely drifted field raises loudly under extra="forbid", never stripped).
        return Pillar.model_validate(pdict)
