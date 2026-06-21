"""Phase 89 Plan 01 — B5 rubric loader.

Loads a rubric YAML from the capability registry via lookup_capability.
Fails fast (no fallback) if the rubric id is not found — Phase 47.6 lock.

Per project locks:
  - env-driven config, no hardcoded URLs, no fallback defaults
  - all capabilities discovered via registry, never hardcoded enumeration
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def load_rubric(rubric_id: str) -> dict:
    """Load a rubric from the capability registry by id.

    Calls lookup_capability(id=rubric_id) and returns the full raw YAML
    payload as a dict (the CapabilitySummary includes the full_meta via
    the registry's side-channel).

    Fails fast with RuntimeError if:
      - The rubric_id is not registered (status "not_available")
      - The resolved capability is not of type "rubric"

    This is intentional: a missing rubric means B5 is misconfigured.
    Silent fallback would let bad answers through without scoring.

    Args:
        rubric_id: Registry id for the rubric (e.g. "rubric.macro_investigator_qa").

    Returns:
        Raw rubric dict with keys: id, checks (list), threshold, refinement,
        graceful_degradation_text, utility_model_routing, word_cap.

    Raises:
        RuntimeError: If rubric_id not found in registry or not type "rubric".
        RuntimeError: If CapabilityRegistry not initialized (boot-time lock).
    """
    try:
        # Import here to avoid circular imports at module load time
        from core.registry.capability_registry import CapabilityRegistry
    except RuntimeError as exc:
        # CapabilityRegistry not initialized — propagate clearly
        raise RuntimeError(
            f"B5 rubric_loader: CapabilityRegistry not initialized. "
            f"Cannot load rubric '{rubric_id}'. "
            f"Ensure CapabilityRegistry.initialize() is called at boot. "
            f"Original error: {exc}"
        ) from exc

    reg = CapabilityRegistry.get()
    summary = reg.lookup(rubric_id)

    if summary is None:
        closest = reg.closest_ids(rubric_id, limit=3)
        raise RuntimeError(
            f"B5 rubric_loader: rubric '{rubric_id}' not found in capability registry. "
            f"Closest matches: {closest}. "
            f"Register the rubric YAML before enabling b5_self_eval on a profile."
        )

    # Return the full metadata dict from the registry (includes all YAML fields)
    raw = reg._full_meta.get(rubric_id)
    if raw is None:
        raise RuntimeError(
            f"B5 rubric_loader: rubric '{rubric_id}' found in registry but "
            f"full metadata missing. This is a registry boot bug."
        )

    logger.debug(
        "b5_rubric_loaded",
        extra={"rubric_id": rubric_id, "check_count": len(raw.get("checks", []))},
    )
    return raw
