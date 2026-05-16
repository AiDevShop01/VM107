"""Phase 61-01 — CounterfactualReader — VM107 helper for reading counterfactual artifacts.

Calls VM100 internal endpoints. Returns structured dicts (not Pydantic models, since
VM107 does not install fingpt_core directly — duck-typed contract matching).

Design constraints:
- Never mounts VM100 filesystem (no cross-VM filesystem reads per Phase 47 lock)
- All data comes via VM100 internal API calls (typed VM API pattern)
- ScopeSpec.counterfactual_visibility filter enforced before returning data
- Experimental scenarios filtered out by default (canonical tier only)
- Returns [] (never raises) when VM100 unavailable — ToolError pattern (Pitfall 11)
- forward-only: only executions processed after PHASE_61_DEPLOY_TS have artifacts (RG-6)

Law #4 invariant: every returned artifact dict has truth_mode='COUNTERFACTUAL'.
Law #9 invariant: artifacts produced by deterministic Python only — never LLM.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# VM100 base URL — from env (no fallback default; fail-fast discipline)
_VM100_INTERNAL_BASE = os.environ.get("VM100_INTERNAL_API_URL")


def _get_vm100_internal_base() -> str:
    """Return VM100 internal API base URL. Raises if not configured (fail-fast)."""
    base = os.environ.get("VM100_INTERNAL_API_URL")
    if not base:
        raise RuntimeError(
            "VM100_INTERNAL_API_URL not set. CounterfactualReader requires "
            "the VM100 internal API to be configured via environment variable. "
            "No fallback default (Phase 47 env-driven config discipline)."
        )
    return base.rstrip("/")


def _apply_visibility_filter(
    artifacts: list[dict],
    counterfactual_visibility: str,
    tier: str,
) -> list[dict]:
    """Apply ScopeSpec.counterfactual_visibility filter to artifact list.

    Args:
        artifacts: Raw artifact dicts from VM100.
        counterfactual_visibility: 'NONE' | 'CANONICAL_ONLY' | 'ALL'
        tier: 'canonical' | 'experimental' | 'all'

    Returns:
        Filtered list per visibility and tier rules.
    """
    if counterfactual_visibility == "NONE":
        return []

    if counterfactual_visibility == "CANONICAL_ONLY":
        # Never return experimental scenarios, regardless of tier parameter
        return [a for a in artifacts if a.get("scenario_tier") == "canonical"]

    # counterfactual_visibility == 'ALL' — apply tier filter
    if tier == "canonical":
        return [a for a in artifacts if a.get("scenario_tier") == "canonical"]
    if tier == "experimental":
        return [a for a in artifacts if a.get("scenario_tier") == "experimental"]
    return artifacts  # tier == 'all'


def get_counterfactuals_for_execution(
    execution_id: str,
    *,
    tier: str = "canonical",
    counterfactual_visibility: str = "CANONICAL_ONLY",
    timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """Return all counterfactual artifacts for a given execution_id.

    Args:
        execution_id: UUID string of the closed Execution.
        tier: 'canonical' | 'experimental' | 'all'. Default 'canonical'.
              Experimental scenarios are NEVER returned when
              counterfactual_visibility='CANONICAL_ONLY' even if tier='all'.
        counterfactual_visibility: Resolved from ScopeSpec at call time.
              'NONE' → []; 'CANONICAL_ONLY' → canonical tier only; 'ALL' → all tiers.
        timeout: Request timeout in seconds.

    Returns:
        List of counterfactual artifact dicts, each with truth_mode='COUNTERFACTUAL' (Law #4).
        Returns [] if no artifacts yet (normal in Phase 61 — zero scenarios shipped).
        Returns [] on VM100 transport failure (ToolError pattern — never raises, Pitfall 11).
    """
    # Fast-path for NONE visibility — no network call needed
    if counterfactual_visibility == "NONE":
        return []

    try:
        import httpx

        base = _get_vm100_internal_base()
        url = f"{base}/api/journal/internal/counterfactuals/{execution_id}"

        response = httpx.get(url, timeout=timeout)
        response.raise_for_status()
        artifacts = response.json()

        if not isinstance(artifacts, list):
            logger.warning(
                "counterfactual_reader_unexpected_response_shape",
                extra={"execution_id": execution_id, "shape": type(artifacts).__name__},
            )
            return []

        # Enforce Law #4: filter out any row that lacks truth_mode='COUNTERFACTUAL'
        valid = [a for a in artifacts if a.get("truth_mode") == "COUNTERFACTUAL"]
        if len(valid) != len(artifacts):
            logger.warning(
                "counterfactual_reader_filtered_non_counterfactual_rows",
                extra={
                    "execution_id": execution_id,
                    "total": len(artifacts),
                    "valid": len(valid),
                },
            )

        return _apply_visibility_filter(valid, counterfactual_visibility, tier)

    except RuntimeError as exc:
        # VM100_INTERNAL_API_URL not configured
        logger.error(
            "counterfactual_reader_config_error",
            extra={"execution_id": execution_id, "error": str(exc)},
        )
        return []
    except Exception as exc:
        # Transport failure / timeout / HTTP error — return [] (Pitfall 11, never raises)
        logger.warning(
            "counterfactual_reader_vm100_unavailable",
            extra={"execution_id": execution_id, "error": str(exc)},
        )
        return []


def get_counterfactual(
    execution_id: str,
    scenario_id: str,
    *,
    scenario_version: str | None = None,
    counterfactual_visibility: str = "CANONICAL_ONLY",
    timeout: float = 15.0,
) -> dict[str, Any] | None:
    """Return a single counterfactual artifact for (execution_id, scenario_id).

    Args:
        execution_id: UUID string of the closed Execution.
        scenario_id: Registry ID of the scenario (e.g. counterfactual.stop.atr_1_0).
        scenario_version: SemVer string; None = latest version for this scenario.
        counterfactual_visibility: Resolved from ScopeSpec.
        timeout: Request timeout in seconds.

    Returns:
        Artifact dict with truth_mode='COUNTERFACTUAL' (Law #4), or None if not found.
        Returns None on 404 or VM100 transport failure (never raises, Pitfall 11).
    """
    if counterfactual_visibility == "NONE":
        return None

    try:
        import httpx

        base = _get_vm100_internal_base()
        url = f"{base}/api/journal/internal/counterfactuals/{execution_id}/{scenario_id}"
        params = {}
        if scenario_version is not None:
            params["scenario_version"] = scenario_version

        response = httpx.get(url, params=params, timeout=timeout)

        if response.status_code == 404:
            return None

        response.raise_for_status()
        artifact = response.json()

        if not isinstance(artifact, dict):
            return None

        # Law #4: reject if truth_mode is not COUNTERFACTUAL
        if artifact.get("truth_mode") != "COUNTERFACTUAL":
            logger.warning(
                "counterfactual_reader_law4_violation",
                extra={
                    "execution_id": execution_id,
                    "scenario_id": scenario_id,
                    "truth_mode": artifact.get("truth_mode"),
                },
            )
            return None

        return artifact

    except RuntimeError as exc:
        logger.error(
            "counterfactual_reader_config_error",
            extra={
                "execution_id": execution_id,
                "scenario_id": scenario_id,
                "error": str(exc),
            },
        )
        return None
    except Exception as exc:
        logger.warning(
            "counterfactual_reader_vm100_unavailable",
            extra={
                "execution_id": execution_id,
                "scenario_id": scenario_id,
                "error": str(exc),
            },
        )
        return None


def lookup_counterfactual_scenario(
    scenario_id: str,
    *,
    timeout: float = 10.0,
) -> dict[str, Any] | None:
    """Return scenario metadata for a registered counterfactual scenario_id.

    Args:
        scenario_id: Registry ID of the scenario.
        timeout: Request timeout in seconds.

    Returns:
        Scenario metadata dict, or None if not found or VM100 unavailable.
        Returns None on 404 or transport failure (never raises, Pitfall 11).
    """
    try:
        import httpx

        base = _get_vm100_internal_base()
        url = f"{base}/api/journal/internal/counterfactuals/scenarios/{scenario_id}"

        response = httpx.get(url, timeout=timeout)

        if response.status_code == 404:
            return None

        response.raise_for_status()
        return response.json()

    except RuntimeError as exc:
        logger.error(
            "counterfactual_reader_config_error",
            extra={"scenario_id": scenario_id, "error": str(exc)},
        )
        return None
    except Exception as exc:
        logger.warning(
            "counterfactual_reader_vm100_unavailable",
            extra={"scenario_id": scenario_id, "error": str(exc)},
        )
        return None
