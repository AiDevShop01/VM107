"""Phase 62-05 — get_pattern_cluster_stats: scope-aware HTTP client tool.

Returns aggregate statistics for a specific PatternClusterSnapshot from VM100.

CTX-DEC-14: Returns None immediately if PATTERN is NOT in adaptive_signal_categories.
CTX-DEC-16: NEVER recomputes live. Reads frozen-snapshot Postgres rows only.
CTX-DEC-17: Returned data carries truth_mode=ADAPTIVE_OBSERVATION.
CTX-DEC-15: SHADOW_ONLY framing — never surfaced in apply UI.
CTX-DEC-13: cluster stats reflect structured vector clustering ONLY.
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

logger = logging.getLogger("fingpt.tools.adaptive.get_pattern_cluster_stats")

# Adaptive signal category enum value — PATTERN scope
_SIGNAL_CATEGORY_VALUE = "PATTERN"

# Env var must be set — NO fallback (MEMORY.md: fail-fast beats silent misconfiguration)
_ENV_VAR = "VM100_INTERNAL_BASE_URL"


async def get_pattern_cluster_stats(
    cluster_snapshot_id: str,
    *,
    adaptive_signal_categories: frozenset,
    http_client: Optional[httpx.AsyncClient] = None,
) -> Optional[dict]:
    """Return aggregate stats for a PatternClusterSnapshot.

    Args:
        cluster_snapshot_id: UUID string of the PatternClusterSnapshot.
        adaptive_signal_categories: frozenset of AdaptiveSignalCategory values
            resolved from ScopeContext at call time. If PATTERN is not present,
            returns None immediately (CTX-DEC-14 defense-in-depth).
        http_client: Optional injected httpx.AsyncClient (for testing).

    Returns:
        dict with PatternClusterSnapshot fields, or None on any error / scope exclusion.
        Fields include: cluster_snapshot_id, cohort_snapshot_id, clustering_method,
        cluster_count, noise_count, total_executions, cluster_labels, cluster_centroids,
        status, truth_mode, generated_at.

    Signal category: PATTERN.
    Endpoint: GET /api/journal/internal/adaptive/pattern-cluster/{cluster_snapshot_id}
    """
    # CTX-DEC-14 defense-in-depth: prune by scope before calling VM100
    category_values = {
        v.value if hasattr(v, "value") else str(v)
        for v in adaptive_signal_categories
    }
    if _SIGNAL_CATEGORY_VALUE not in category_values:
        logger.debug(
            "get_pattern_cluster_stats: PATTERN not in adaptive_signal_categories=%r "
            "— returning None (CTX-DEC-14)",
            adaptive_signal_categories,
        )
        return None

    # NO fallback — fail fast at call time if env var missing (MEMORY.md)
    base_url = os.environ[_ENV_VAR]
    url = (
        f"{base_url}/api/journal/internal/adaptive/"
        f"pattern-cluster/{cluster_snapshot_id}"
    )

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=15.0)
    try:
        response = await client.get(url)
        if response.status_code == 404:
            logger.debug(
                "get_pattern_cluster_stats: snapshot not found for cluster_snapshot_id=%s",
                cluster_snapshot_id,
            )
            return None
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else None
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "get_pattern_cluster_stats: HTTP error %d for cluster_snapshot_id=%s",
            exc.response.status_code, cluster_snapshot_id,
        )
        return None
    except Exception as exc:
        logger.warning(
            "get_pattern_cluster_stats: error for cluster_snapshot_id=%s: %s",
            cluster_snapshot_id, exc,
        )
        return None
    finally:
        if owns_client:
            await client.aclose()
