"""Phase 62-05 — get_pattern_cluster_membership: scope-aware HTTP client tool.

Returns cluster membership for a given execution_id from VM100.

CTX-DEC-14: Returns [] immediately if PATTERN is NOT in adaptive_signal_categories.
    The MentorPipelineOrchestrator ALSO prunes BEFORE planning — this is defense-in-depth.
CTX-DEC-16: NEVER recomputes live. Reads frozen-snapshot Postgres rows only.
CTX-DEC-17: Returned rows carry truth_mode=ADAPTIVE_OBSERVATION.
CTX-DEC-15: SHADOW_ONLY framing — never surfaced in apply UI.
CTX-DEC-13: cluster membership reflects structured vector clustering ONLY.
    NO narrative/LLM substrate. Cluster labels are deterministic centroid-hash descriptors.

No SQL access. No parquet reads. Pure HTTP client.
VM100_INTERNAL_BASE_URL env var — NO fallback default (MEMORY.md env-driven-no-fallbacks).

PATTERN scope: this tool is ONLY available when PATTERN in adaptive_signal_categories.
PATTERN is NOT in behavioral_mentor's category set (plan spec: Task 3 verification).

Doctrine:
    Phase 62 does NOT optimize. It proposes adaptive hypotheses.
    Humans authorize epistemic change.
    Adaptive outputs are advisory cognition artifacts. Never canonical trading truth.
"""

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("fingpt.tools.adaptive.get_pattern_cluster_membership")

# Adaptive signal category enum value — PATTERN scope
_SIGNAL_CATEGORY_VALUE = "PATTERN"

# Env var must be set — NO fallback (MEMORY.md: fail-fast beats silent misconfiguration)
_ENV_VAR = "VM100_INTERNAL_BASE_URL"


async def get_pattern_cluster_membership(
    execution_id: str,
    *,
    adaptive_signal_categories: frozenset,
    http_client: Optional[httpx.AsyncClient] = None,
) -> list:
    """Return cluster membership for a given execution_id.

    Looks up the most recent PatternClusterSnapshot that contains this execution.

    Args:
        execution_id: UUID string of the trade execution.
        adaptive_signal_categories: frozenset of AdaptiveSignalCategory values
            resolved from ScopeContext at call time. If PATTERN is not present,
            returns [] immediately (CTX-DEC-14 defense-in-depth).
        http_client: Optional injected httpx.AsyncClient (for testing).
            If None, a fresh client is created and closed after the request.

    Returns:
        list[dict]: [{cluster_id, cluster_label, cluster_snapshot_id, generated_at,
                      truth_mode}] or [] on any error / scope exclusion.

    Signal category: PATTERN.
    Endpoint: GET /api/journal/internal/adaptive/pattern-cluster-membership/{execution_id}
    """
    # CTX-DEC-14 defense-in-depth: prune by scope before calling VM100
    category_values = {
        v.value if hasattr(v, "value") else str(v)
        for v in adaptive_signal_categories
    }
    if _SIGNAL_CATEGORY_VALUE not in category_values:
        logger.debug(
            "get_pattern_cluster_membership: PATTERN not in adaptive_signal_categories=%r "
            "— returning [] (CTX-DEC-14)",
            adaptive_signal_categories,
        )
        return []

    # NO fallback — fail fast at call time if env var missing (MEMORY.md)
    base_url = os.environ[_ENV_VAR]
    url = (
        f"{base_url}/api/journal/internal/adaptive/"
        f"pattern-cluster-membership/{execution_id}"
    )

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=15.0)
    try:
        response = await client.get(url)
        if response.status_code == 404:
            logger.debug(
                "get_pattern_cluster_membership: no membership found for execution_id=%s",
                execution_id,
            )
            return []
        response.raise_for_status()
        data = response.json()
        # Return as single-item list for consistent interface
        return [data] if isinstance(data, dict) else []
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "get_pattern_cluster_membership: HTTP error %d for execution_id=%s",
            exc.response.status_code, execution_id,
        )
        return []
    except Exception as exc:
        logger.warning(
            "get_pattern_cluster_membership: error for execution_id=%s: %s",
            execution_id, exc,
        )
        return []
    finally:
        if owns_client:
            await client.aclose()
