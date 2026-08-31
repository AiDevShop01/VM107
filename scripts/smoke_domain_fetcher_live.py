"""Phase 156 Plan 02 (D-04 tier 2) — one-shot LIVE dev-VM100 domain-fetch smoke.

Resolves RESEARCH assumption **A1**: whether the *real* dev-VM100
``/api/macro-situation/domain/{slug}`` endpoint returns JSON that validates
cleanly into the VM107-local frozen ``Domain`` (``extra="forbid"``). CI only
proves this against a contract-faithful fake; this host-run script is the
mandated gate that proves the real serialization round-trips (the BLOCKING
live-verify is Plan 156-03).

Usage (host / dev-run — NOT a container path)::

    VM107/.venv/bin/python scripts/smoke_domain_fetcher_live.py inflation US

Exit-code contract (mirrors ``scripts/macro_regime_monitor_health.py``):
  * ``0`` + ``healthy:`` on stdout — the fetcher returned a validated ``Domain``
    whose ``.slug`` matches the requested slug (``Domain.model_validate``
    succeeded under ``extra="forbid"``).
  * ``1`` + ``unhealthy:`` on stderr — any of: missing/blank args, a ``None``
    result (404 snapshot-not-ready → operator retries), a ``ValidationError``
    (live shape drift → the A1 failure the smoke exists to catch), an HTTP
    status error, or a transient network error.

Security (T-156-03): this script NEVER prints the ``VM107_SERVICE_JWT`` value.
The fetcher reads it from the environment; only the var *name* is ever named
in diagnostics.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone


def _main() -> int:
    # --- Arg parsing FIRST -------------------------------------------------
    # Parse/validate argv before importing the fetcher: the fetcher module
    # reads VM100_API_URL / VM107_SERVICE_JWT at import (fail-fast), so a
    # no-arg invocation must fail with a clean usage message, not an env
    # KeyError traceback.
    argv = sys.argv[1:]
    if len(argv) != 2 or not argv[0].strip() or not argv[1].strip():
        sys.stderr.write(
            "unhealthy: usage: python scripts/smoke_domain_fetcher_live.py "
            "<slug> <country>\n"
            "  e.g. python scripts/smoke_domain_fetcher_live.py inflation US\n"
        )
        return 1

    slug = argv[0].strip()
    country = argv[1].strip().upper()

    # --- Lazy imports (after args validated) -------------------------------
    # Import here so a bad-args run never triggers the fetcher's import-time
    # fail-fast env read.
    try:
        from pydantic import ValidationError

        from agents.domain_analyst_subscriber.domain_fetcher import (
            DomainSnapshotFetcher,
        )
        from contracts.economic_intelligence.domain import Domain
        from contracts.economic_intelligence.events import (
            EconomicEvent,
            EventSeverity,
            EventType,
        )
    except KeyError as exc:  # missing VM100_API_URL / VM107_SERVICE_JWT
        sys.stderr.write(
            f"unhealthy: required env var missing at fetcher import: {exc} "
            "(export VM100_API_URL and VM107_SERVICE_JWT before running)\n"
        )
        return 1

    # --- Build a minimal valid live event ----------------------------------
    try:
        event = EconomicEvent(
            event_id="smoke-domain-fetcher-live",
            event_type=EventType.MACRO_RELEASE,
            severity=EventSeverity.LOW,
            country=country,
            occurred_at=datetime.now(tz=timezone.utc),
            source="scripts.smoke_domain_fetcher_live",
            payload={},
        )
    except ValidationError as exc:
        sys.stderr.write(
            f"unhealthy: invalid country {country!r} — must be ISO 3166-1 "
            f"alpha-2 uppercase (e.g. 'US'): {exc}\n"
        )
        return 1

    # --- Live fetch against dev-VM100 --------------------------------------
    try:
        fetcher = DomainSnapshotFetcher()  # reads real VM100_API_URL + JWT
        domain = fetcher(slug, event)
    except ValidationError as exc:
        # This is the A1 failure the smoke exists to catch: VM100's live JSON
        # did NOT round-trip into the VM107-local frozen Domain (extra="forbid").
        sys.stderr.write(
            f"unhealthy: VM100 domain JSON failed Domain.model_validate for "
            f"slug={slug} country={country} — live shape drift (assumption A1 "
            f"FAILED; fix with a thin field-adapter, never relax extra=forbid):\n"
            f"{exc}\n"
        )
        return 1
    except Exception as exc:  # httpx status / network / RuntimeError
        # Never print the JWT — only the exception type + message (the fetcher
        # already refuses to embed the token in its error strings).
        sys.stderr.write(
            f"unhealthy: live fetch failed for slug={slug} country={country}: "
            f"{type(exc).__name__}: {exc}\n"
        )
        return 1

    # --- Assert a validated Domain with a matching slug --------------------
    if domain is None:
        sys.stderr.write(
            f"unhealthy: no snapshot for slug={slug} country={country} "
            "(404 not-ready or unknown slug) — retry once the snapshot lands\n"
        )
        return 1

    if not isinstance(domain, Domain):
        sys.stderr.write(
            f"unhealthy: fetcher returned {type(domain).__name__}, expected a "
            f"validated Domain for slug={slug}\n"
        )
        return 1

    if domain.slug != slug:
        sys.stderr.write(
            f"unhealthy: Domain.slug mismatch — requested {slug!r} but got "
            f"{domain.slug!r} (invoke() would fail its slug assert)\n"
        )
        return 1

    sys.stdout.write(
        f"healthy: live VM100 returned a validated Domain for slug={slug} "
        f"country={country} (Domain.model_validate OK under extra=forbid; "
        f"health_score={domain.health_score}, status={domain.status})\n"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — one-shot host/dev-run smoke
    sys.exit(_main())
