"""Phase 168 Plan 05 — per-facet composers for the EvidencePackAssembler.

Each composer takes the assembler's ``AssemblyContext`` and returns a typed
``tiers.FacetOutcome`` (a populated pack sub-model on success, or a typed
FacetIntegrity failure — NEVER a raise). Composers reach VM102 data ONLY through
typed client seams (G10): never a raw parquet/DB store, never ``compute_domain``.

``reuse_composers()`` returns the four reuse/typed facets (domain_state /
state_diff / contribution / contradiction) the assembler registers over its
deferred-placeholder defaults. The net-new signal_importance /
historical_context / prior_assessment facets land in 168-06.

Task 1 ships this package with an empty registry (the assembler's honest
UNAVAILABLE defaults stand); Task 2 wires the real composers.
"""

from __future__ import annotations

from typing import Callable

__all__ = ["reuse_composers"]


def reuse_composers() -> dict[str, Callable]:
    """Return the reuse/typed facet composers to register on the assembler.

    Populated in Plan-05 Task 2. Until then the assembler keeps its honest
    UNAVAILABLE defaults for the reuse facets.
    """
    return {}
