"""Phase 62-04 — get_behavioral_evolution: scope-aware HTTP client tool.

Reads frozen BehavioralEvolutionSeries rows from VM100 internal endpoint.

CTX-DEC-14: Returns [] immediately if BEHAVIORAL is NOT in adaptive_signal_categories.
    The MentorPipelineOrchestrator ALSO prunes BEFORE planning — this is defense-in-depth.
CTX-DEC-16: NEVER recomputes live. Reads frozen-snapshot Postgres rows only.
CTX-DEC-17: Returned rows carry truth_mode=ADAPTIVE_OBSERVATION.
CTX-DEC-15: SHADOW_ONLY framing — never surfaced in apply UI.
CTX-DEC-12: 4 LOCKED behavioral metric families. NO psychological labels.

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

logger = logging.getLogger("fingpt.tools.adaptive.get_behavioral_evolution")

# Adaptive signal category enum value — BEHAVIORAL evolution surface
_SIGNAL_CATEGORY_VALUE = "BEHAVIORAL"

# Env var must be set — NO fallback (MEMORY.md: fail-fast beats silent misconfiguration)
_ENV_VAR = "VM100_INTERNAL_BASE_URL"


async def get_behavioral_evolution(
    account_id: str,
    cohort_snapshot_id: str,
    *,
    adaptive_signal_categories: frozenset,
    http_client: Optional[httpx.AsyncClient] = None,
) -> list:
    """Return persisted BehavioralEvolutionSeries rows for an account + frozen cohort snapshot.

    Args:
        account_id: UUID string of the trader account.
        cohort_snapshot_id: UUID string of the frozen CohortSnapshot.
        adaptive_signal_categories: frozenset of AdaptiveSignalCategory values
            resolved from ScopeContext at call time. If BEHAVIORAL is not present,
            returns [] immediately (CTX-DEC-14 defense-in-depth).
        http_client: Optional injected httpx.AsyncClient (for testing).
            If None, a fresh client is created and closed after the request.

    Returns:
        list[dict]: Rows from BehavioralEvolutionSeries (truth_mode=ADAPTIVE_OBSERVATION).
        Empty list if: BEHAVIORAL not in scope, cohort not found (404), or error.

    Signal category: BEHAVIORAL.
    Endpoint: GET /api/journal/internal/adaptive/behavioral-evolution/{account_id}/{cohort_snapshot_id}
    """
    # CTX-DEC-14 defense-in-depth: prune by scope before calling VM100
    # Accepts both enum instances and string values for flexibility
    category_values = {
        v.value if hasattr(v, "value") else str(v)
        for v in adaptive_signal_categories
    }
    if _SIGNAL_CATEGORY_VALUE not in category_values:
        logger.debug(
            "get_behavioral_evolution: BEHAVIORAL not in adaptive_signal_categories=%r — returning [] (CTX-DEC-14)",
            adaptive_signal_categories,
        )
        return []

    # NO fallback — fail fast at call time if env var missing (MEMORY.md)
    base_url = os.environ[_ENV_VAR]
    url = f"{base_url}/api/journal/internal/adaptive/behavioral-evolution/{account_id}/{cohort_snapshot_id}"

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=15.0)
    try:
        resp = await client.get(url)
        if resp.status_code == 404:
            logger.debug(
                "get_behavioral_evolution: 404 for account_id=%s cohort_snapshot_id=%s — no BehavioralEvolutionSeries yet",
                account_id,
                cohort_snapshot_id,
            )
            return []
        resp.raise_for_status()
        payload = resp.json()
        rows = payload.get("rows", [])
        logger.debug(
            "get_behavioral_evolution: returned %d rows for account_id=%s cohort_snapshot_id=%s",
            len(rows),
            account_id,
            cohort_snapshot_id,
        )
        return rows
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "get_behavioral_evolution: HTTP error %s for account_id=%s cohort_snapshot_id=%s: %s",
            exc.response.status_code,
            account_id,
            cohort_snapshot_id,
            exc,
        )
        return []
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.warning(
            "get_behavioral_evolution: transport error for account_id=%s cohort_snapshot_id=%s: %s",
            account_id,
            cohort_snapshot_id,
            exc,
        )
        return []
    finally:
        if owns_client:
            await client.aclose()
