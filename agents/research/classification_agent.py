"""Phase 92 Plan 03 — ResearchClassificationAgent orchestration.

Orchestrates ``tier_classifier + indicator_linker + asset_linker`` for one
ResearchDocument. Owns the Pitfall-3 soft-reject rule: if NEITHER Stage 1
NOR Stage 2 returns any indicator hits, the result is ``status='unlinked'``
with ``reject_reason='no_indicator_link'`` (the document is KEPT in
research_document for human review — not silently dropped).

Public API:

    agent = ResearchClassificationAgent()
    result = agent.classify(
        doc_text=...,
        doc_title=...,
        acquisition_stream=...,
        source_id=...,
    )

Returns a ``ClassificationResult`` dataclass carrying the same shape the
VM101 pipeline writes back to the ResearchDocument row.

Phase 70.5 envelope:
- This agent does NOT propose beliefs (deterministic+LLM-augmented, not
  free-form narrative).
- ``is_deterministic`` = false on the registry profile (Stage 2 LLM
  fallback introduces non-determinism); per-emit confidence is carried in
  the ``classifications`` dict on the ResearchDocument.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The tier_classifier lives on VM101 (per separation of concerns in Plan 03 —
# Postgres-adjacent rule tables stay on the receiver side). VM107 imports it
# via a small mirror that reads from the env var ``VM101_TIER_CLASSIFIER_URL``
# when running cross-VM, but for the host-shell harness AND for production
# (where the agent is in-process with the VM101 receiver in a Django shell
# command), we provide a small local-import shim.

try:
    # When VM101 is on PYTHONPATH (e.g. tests run from a monorepo checkout
    # or production wires VM101's classification package into VM107's sys.path)
    from knowledge.research.classification.tier_classifier import classify_tier
except ImportError:  # pragma: no cover — exercised in pure-VM107 deployments
    # Local mirror — same routing table as VM101's tier_classifier. Drift is
    # caught by the Plan 4 regression that asserts both copies produce the
    # same (tier, confidence) tuple for a fixed input set.
    _TIER_1_PREFIXES: tuple[str, ...] = (
        "fed_", "ecb_", "boe_", "boj_", "bis_", "imf_", "oecd_",
    )
    _TIER_3_PREFIXES: tuple[str, ...] = ("arxiv_", "nber_", "ssrn_")
    _TIER_4_PREFIXES: tuple[str, ...] = ("mr_", "sellside_", "research_")
    _TIER_5_PREFIXES: tuple[str, ...] = ("manual_", "agent_", "discovery_")

    def classify_tier(source_id: str, acquisition_stream: str) -> tuple[int, float]:
        sid = (source_id or "").strip().lower()
        stream = (acquisition_stream or "").strip().upper()
        if stream in ("D", "E"):
            return (5, 1.0)
        if sid.startswith(_TIER_1_PREFIXES):
            return (1, 1.0)
        if sid.startswith(_TIER_3_PREFIXES):
            return (3, 1.0)
        if sid.startswith(_TIER_4_PREFIXES):
            return (4, 0.9)
        if sid.startswith(_TIER_5_PREFIXES):
            return (5, 1.0)
        return (2, 0.1)


from agents.research.asset_linker import link_assets
from agents.research.indicator_linker import link_indicators


@dataclass
class ClassificationResult:
    """Plan 3 classifier output. Mirrors the ResearchDocument columns
    populated by the VM101 pipeline.
    """
    tier: int
    indicators: list[str]
    assets: list[str]
    status: str  # 'classified' | 'unlinked' | 'rejected'
    reject_reason: str | None = None
    classifications: dict[str, Any] = field(default_factory=dict)


class ResearchClassificationAgent:
    """Pipeline orchestrator: tier → indicators → assets → status."""

    def classify(
        self,
        doc_text: str,
        doc_title: str,
        acquisition_stream: str,
        source_id: str,
    ) -> ClassificationResult:
        # ── Step 1: tier ────────────────────────────────────────────────
        tier, tier_confidence = classify_tier(source_id, acquisition_stream)

        # ── Step 2: indicator linking (Stage 1 + 2) ─────────────────────
        try:
            indicator_hits, linker_stage = link_indicators(
                doc_text=doc_text, doc_title=doc_title
            )
        except Exception as e:
            # Any unexpected failure during linking → status='rejected'
            # (NOT 'unlinked'; the doc was processable but the pipeline
            # itself erred out, which is operator-visible).
            return ClassificationResult(
                tier=tier,
                indicators=[],
                assets=[],
                status="rejected",
                reject_reason=f"linker_error: {type(e).__name__}",
                classifications={
                    "tier_confidence": tier_confidence,
                    "linker_stage": "error",
                    "error_class": type(e).__name__,
                },
            )

        indicator_ids = [h["indicator_id"] for h in indicator_hits]

        # ── Step 3: Pitfall 3 soft-reject ───────────────────────────────
        if not indicator_ids:
            return ClassificationResult(
                tier=tier,
                indicators=[],
                assets=[],
                status="unlinked",
                reject_reason="no_indicator_link",
                classifications={
                    "tier_confidence": tier_confidence,
                    "linker_stage": "none",
                },
            )

        # ── Step 4: asset linking ───────────────────────────────────────
        asset_hits = link_assets(indicator_ids)
        asset_ids = [a["asset_id"] for a in asset_hits]

        # ── Step 5: success envelope ────────────────────────────────────
        classifications: dict[str, Any] = {
            "tier_confidence": tier_confidence,
            "linker_stage": linker_stage,
            "indicator_count": len(indicator_ids),
            "asset_count": len(asset_ids),
        }
        # Carry the max LLM confidence forward when relevant (Phase 70.5 envelope)
        if linker_stage == "llm":
            classifications["llm_confidence"] = max(
                (h.get("confidence", 0.0) for h in indicator_hits), default=0.0
            )

        return ClassificationResult(
            tier=tier,
            indicators=indicator_ids,
            assets=asset_ids,
            status="classified",
            reject_reason=None,
            classifications=classifications,
        )


__all__ = ["ResearchClassificationAgent", "ClassificationResult"]
