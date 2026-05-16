"""Phase 62-03 — get_counterfactual_scenario_stats: scope-aware HTTP client tool.

Reads frozen CounterfactualAggregateSnapshot from VM100 internal endpoint.

CTX-DEC-14: Returns None immediately if COUNTERFACTUAL_AGGREGATE is NOT in
    adaptive_signal_categories. Defense-in-depth (orchestrator prunes BEFORE planning).
CTX-DEC-16: NEVER recomputes live. Reads frozen-snapshot Postgres rows only.
CTX-DEC-17: Returned data carries truth_mode=ADAPTIVE_OBSERVATION.
CTX-DEC-15: SHADOW_ONLY framing — never surfaced in apply UI.

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

logger = logging.getLogger("fingpt.tools.adaptive.get_counterfactual_scenario_stats")

# Adaptive signal category enum value — COUNTERFACTUAL_AGGREGATE surface
_SIGNAL_CATEGORY_VALUE = "COUNTERFACTUAL_AGGREGATE"

# Env var must be set — NO fallback (MEMORY.md: fail-fast beats silent misconfiguration)
_ENV_VAR = "VM100_INTERNAL_BASE_URL"


async def get_counterfactual_scenario_stats(
    scenario_id: str,
    cohort_snapshot_id: str,
    *,
    adaptive_signal_categories: frozenset,
    http_client: Optional[httpx.AsyncClient] = None,
) -> Optional[dict]:
    """Return persisted CounterfactualAggregateSnapshot for (scenario, cohort) pair.

    Args:
        scenario_id: Scenario identifier string.
        cohort_snapshot_id: UUID string of the frozen CohortSnapshot.
        adaptive_signal_categories: frozenset of AdaptiveSignalCategory values
            resolved from ScopeContext at call time. If COUNTERFACTUAL_AGGREGATE
            is not present, returns None immediately (CTX-DEC-14 defense-in-depth).
        http_client: Optional injected httpx.AsyncClient (for testing).
            If None, a fresh client is created and closed after the request.

    Returns:
        dict: Serialized CounterfactualAggregateSnapshot (truth_mode=ADAPTIVE_OBSERVATION).
        None if: COUNTERFACTUAL_AGGREGATE not in scope, not found (404), or error.

    Signal category: COUNTERFACTUAL_AGGREGATE.
    Endpoint: GET /api/journal/internal/adaptive/counterfactual-aggregate/{scenario_id}/{cohort_snapshot_id}
    """
    # CTX-DEC-14 defense-in-depth: prune by scope before calling VM100
    category_values = {
        v.value if hasattr(v, "value") else str(v)
        for v in adaptive_signal_categories
    }
    if _SIGNAL_CATEGORY_VALUE not in category_values:
        logger.debug(
            "get_counterfactual_scenario_stats: COUNTERFACTUAL_AGGREGATE not in "
            "adaptive_signal_categories=%r — returning None (CTX-DEC-14)",
            adaptive_signal_categories,
        )
        return None

    # NO fallback — fail fast at call time if env var missing (MEMORY.md)
    base_url = os.environ[_ENV_VAR]
    url = (
        f"{base_url}/api/journal/internal/adaptive/counterfactual-aggregate"
        f"/{scenario_id}/{cohort_snapshot_id}"
    )

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=15.0)
    try:
        resp = await client.get(url)
        if resp.status_code == 404:
            logger.debug(
                "get_counterfactual_scenario_stats: 404 for scenario_id=%s cohort_snapshot_id=%s",
                scenario_id,
                cohort_snapshot_id,
            )
            return None
        resp.raise_for_status()
        payload = resp.json()
        logger.debug(
            "get_counterfactual_scenario_stats: returned snapshot for scenario_id=%s cohort_snapshot_id=%s",
            scenario_id,
            cohort_snapshot_id,
        )
        return payload
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "get_counterfactual_scenario_stats: HTTP error %s for scenario_id=%s: %s",
            exc.response.status_code,
            scenario_id,
            exc,
        )
        return None
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.warning(
            "get_counterfactual_scenario_stats: transport error for scenario_id=%s: %s",
            scenario_id,
            exc,
        )
        return None
    finally:
        if owns_client:
            await client.aclose()
