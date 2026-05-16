"""Phase 62-03 — get_behavioral_drift_summary: scope-aware HTTP client tool.

Reads frozen DriftReport rows from VM100 internal endpoint, filtered to
BEHAVIORAL signal_category only.

CTX-DEC-14: Returns [] immediately if BEHAVIORAL is NOT in adaptive_signal_categories.
    Defense-in-depth (orchestrator prunes BEFORE planning).
CTX-DEC-16: NEVER recomputes live. Reads frozen-snapshot Postgres rows only.
CTX-DEC-17: Returned rows carry truth_mode=ADAPTIVE_OBSERVATION.
CTX-DEC-15: SHADOW_ONLY framing — never surfaced in apply UI.

Phase 62.2 note: This tool returns BEHAVIORAL-tagged rows from the drift_report
endpoint. Phase 62.2 (Behavioral Evolution Layer) will add dedicated behavioral
metrics. For now, this tool filters the drift_report endpoint by signal_category=BEHAVIORAL.

No SQL access. No parquet reads. Pure HTTP client.
VM100_INTERNAL_BASE_URL env var — NO fallback default (MEMORY.md env-driven-no-fallbacks).

Doctrine:
    Phase 62 does NOT optimize. It proposes adaptive hypotheses.
    Humans authorize epistemic change.
    Adaptive outputs are advisory cognition artifacts. Never canonical trading truth.
"""

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("fingpt.tools.adaptive.get_behavioral_drift_summary")

# Adaptive signal category enum value — BEHAVIORAL drift surface
_SIGNAL_CATEGORY_VALUE = "BEHAVIORAL"

# Env var must be set — NO fallback (MEMORY.md: fail-fast beats silent misconfiguration)
_ENV_VAR = "VM100_INTERNAL_BASE_URL"


async def get_behavioral_drift_summary(
    cohort_snapshot_id: str,
    *,
    adaptive_signal_categories: frozenset,
    http_client: Optional[httpx.AsyncClient] = None,
) -> list:
    """Return BEHAVIORAL-tagged DriftReport rows for a frozen cohort snapshot.

    Fetches the full drift report from VM100 and filters rows whose
    signal_category == BEHAVIORAL. In Phase 62.2, the drift_report endpoint
    will produce dedicated behavioral rows; for now, filtering is the mechanism.

    Args:
        cohort_snapshot_id: UUID string of the frozen CohortSnapshot.
        adaptive_signal_categories: frozenset of AdaptiveSignalCategory values
            resolved from ScopeContext at call time. If BEHAVIORAL is not present,
            returns [] immediately (CTX-DEC-14 defense-in-depth).
        http_client: Optional injected httpx.AsyncClient (for testing).
            If None, a fresh client is created and closed after the request.

    Returns:
        list[dict]: Rows from the DriftReport filtered to signal_category=BEHAVIORAL.
        Empty list if: BEHAVIORAL not in scope, cohort not found (404), or error.

    Signal category: BEHAVIORAL.
    Endpoint: GET /api/journal/internal/adaptive/drift-report/{cohort_snapshot_id}
        (same endpoint as get_drift_report — filtered to BEHAVIORAL rows)
    """
    # CTX-DEC-14 defense-in-depth: prune by scope before calling VM100
    category_values = {
        v.value if hasattr(v, "value") else str(v)
        for v in adaptive_signal_categories
    }
    if _SIGNAL_CATEGORY_VALUE not in category_values:
        logger.debug(
            "get_behavioral_drift_summary: BEHAVIORAL not in adaptive_signal_categories=%r "
            "— returning [] (CTX-DEC-14)",
            adaptive_signal_categories,
        )
        return []

    # NO fallback — fail fast at call time if env var missing (MEMORY.md)
    base_url = os.environ[_ENV_VAR]
    url = f"{base_url}/api/journal/internal/adaptive/drift-report/{cohort_snapshot_id}"

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=15.0)
    try:
        resp = await client.get(url)
        if resp.status_code == 404:
            logger.debug(
                "get_behavioral_drift_summary: 404 for cohort_snapshot_id=%s — no DriftReport yet",
                cohort_snapshot_id,
            )
            return []
        resp.raise_for_status()
        payload = resp.json()
        all_rows = payload.get("rows", [])

        # Filter to BEHAVIORAL rows only — Phase 62.2 will add dedicated rows
        behavioral_rows = [
            row for row in all_rows
            if row.get("signal_category") == _SIGNAL_CATEGORY_VALUE
        ]
        logger.debug(
            "get_behavioral_drift_summary: %d/%d BEHAVIORAL rows for cohort_snapshot_id=%s",
            len(behavioral_rows),
            len(all_rows),
            cohort_snapshot_id,
        )
        return behavioral_rows
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "get_behavioral_drift_summary: HTTP error %s for cohort_snapshot_id=%s: %s",
            exc.response.status_code,
            cohort_snapshot_id,
            exc,
        )
        return []
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.warning(
            "get_behavioral_drift_summary: transport error for cohort_snapshot_id=%s: %s",
            cohort_snapshot_id,
            exc,
        )
        return []
    finally:
        if owns_client:
            await client.aclose()
