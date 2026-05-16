"""Phase 62-06 — get_regime_adaptation_candidates: scope-aware HTTP client tool.

Returns regime-scoped AdaptiveRecommendation candidates for a given cohort_snapshot_id
from VM100.

CTX-DEC-14: Returns [] immediately if REGIME_ADAPTATION NOT in adaptive_signal_categories.
    The MentorPipelineOrchestrator ALSO prunes BEFORE planning — this is defense-in-depth.
CTX-DEC-15: SHADOW_ONLY framing — never surfaced in apply UI.
    Tool enforces at call layer: raises ToolError if _shadow_only missing or False (RG-11).
CTX-DEC-16: NEVER recomputes live. Reads frozen-snapshot Postgres rows only.
CTX-DEC-17: Returned rows carry truth_mode=ADAPTIVE_OBSERVATION.
RG-11: Envelope flag is a load-bearing defense-in-depth layer at tool level.
    If VM100 response lacks _shadow_only=True, tool REFUSES to surface candidates.

Regime-scoped variant: filters AdaptiveRecommendation rows by regime context.
Complements get_adaptive_recommendations (all recommendations for a cohort).
This tool surfaces the regime-specific adaptation hypothesis subset.

No SQL access. No parquet reads. Pure HTTP client.
VM100_INTERNAL_BASE_URL env var — NO fallback default (MEMORY.md env-driven-no-fallbacks).

REGIME_ADAPTATION scope: this tool is ONLY available when REGIME_ADAPTATION
in adaptive_signal_categories.

Doctrine:
    Phase 62 does NOT optimize. It proposes adaptive hypotheses.
    Humans authorize epistemic change.
    Adaptive outputs are advisory cognition artifacts. Never canonical trading truth.
"""

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("fingpt.tools.adaptive.get_regime_adaptation_candidates")

# Adaptive signal category enum value — REGIME_ADAPTATION scope
_SIGNAL_CATEGORY_VALUE = "REGIME_ADAPTATION"

# Env var must be set — NO fallback (MEMORY.md: fail-fast beats silent misconfiguration)
_ENV_VAR = "VM100_INTERNAL_BASE_URL"


class ToolError(RuntimeError):
    """Raised when tool-layer invariant is violated.

    RG-11 + CTX-DEC-15: Used to enforce SHADOW_ONLY envelope framing.
    If VM100 response lacks _shadow_only=True, the tool refuses to surface
    regime adaptation candidates to the mentor. Defense-in-depth at tool layer.
    """


async def get_regime_adaptation_candidates(
    cohort_snapshot_id: str,
    *,
    adaptive_signal_categories: frozenset,
    http_client: Optional[httpx.AsyncClient] = None,
) -> list:
    """Return regime-scoped AdaptiveRecommendation candidate rows for a cohort snapshot.

    Fetches regime adaptation candidate rows from the VM100 adaptive endpoint.
    Enforces SHADOW_ONLY envelope framing at the tool layer (RG-11 / CTX-DEC-15).

    Args:
        cohort_snapshot_id: UUID string of the cohort snapshot.
        adaptive_signal_categories: frozenset of AdaptiveSignalCategory values
            resolved from ScopeContext at call time. If REGIME_ADAPTATION is not
            present, returns [] immediately (CTX-DEC-14 defense-in-depth).
        http_client: Optional injected httpx.AsyncClient (for testing).
            If None, a fresh async context-managed client is created.

    Returns:
        list[dict]: Regime adaptation candidate rows or [] on scope exclusion / 404.

    Raises:
        ToolError: If VM100 response envelope is missing _shadow_only=True (RG-11).
        KeyError: If VM100_INTERNAL_BASE_URL env var is not set.

    Signal category: REGIME_ADAPTATION.
    Endpoint: GET /api/journal/internal/adaptive/regime-adaptation-candidates/{cohort_snapshot_id}
    """
    # CTX-DEC-14 defense-in-depth: prune by scope before calling VM100
    category_values = {
        v.value if hasattr(v, "value") else str(v)
        for v in adaptive_signal_categories
    }
    if _SIGNAL_CATEGORY_VALUE not in category_values:
        logger.debug(
            "get_regime_adaptation_candidates: REGIME_ADAPTATION not in "
            "adaptive_signal_categories=%r — returning [] (CTX-DEC-14)",
            adaptive_signal_categories,
        )
        return []

    # NO fallback — fail fast at call time if env var missing (MEMORY.md)
    base_url = os.environ[_ENV_VAR]
    url = (
        f"{base_url}/api/journal/internal/adaptive/"
        f"regime-adaptation-candidates/{cohort_snapshot_id}"
    )

    async def _do_request(client: httpx.AsyncClient) -> list:
        response = await client.get(url)
        if response.status_code == 404:
            logger.debug(
                "get_regime_adaptation_candidates: no candidates found for "
                "cohort_snapshot_id=%s",
                cohort_snapshot_id,
            )
            return []
        response.raise_for_status()
        payload = response.json()

        # RG-11 + CTX-DEC-15: enforce SHADOW_ONLY envelope at tool layer
        # If _shadow_only is missing or False, refuse to surface candidates.
        # This is load-bearing defense-in-depth — VM100 MUST assert the flag.
        if not payload.get("_shadow_only", False):
            raise ToolError(
                "Regime adaptation candidates response missing SHADOW_ONLY framing. "
                "VM100 must include '_shadow_only': True in every adaptive envelope. "
                "RG-11 / CTX-DEC-15: tool refuses to surface candidates without "
                "explicit SHADOW_ONLY assertion."
            )

        rows = payload.get("rows", [])
        logger.debug(
            "get_regime_adaptation_candidates: returned %d rows for "
            "cohort_snapshot_id=%s",
            len(rows),
            cohort_snapshot_id,
        )
        return rows

    try:
        if http_client is not None:
            return await _do_request(http_client)
        async with httpx.AsyncClient(timeout=15.0) as client:
            return await _do_request(client)
    except ToolError:
        # Re-raise ToolError — do NOT swallow it in the generic handler below
        raise
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "get_regime_adaptation_candidates: HTTP error %d for cohort_snapshot_id=%s",
            exc.response.status_code,
            cohort_snapshot_id,
        )
        return []
    except Exception as exc:
        logger.warning(
            "get_regime_adaptation_candidates: error for cohort_snapshot_id=%s: %s",
            cohort_snapshot_id,
            exc,
        )
        return []
