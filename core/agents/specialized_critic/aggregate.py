"""Phase 170 Plan 04 Task 1 (D-05) — the pure reject-ceiling panel aggregator.

PURE FUNCTION. No Mongo. No LLM. No registry. No wall-clock. Inputs in
(the five per-lens `CriticVerdict`s), one aggregate `CriticVerdict` out —
the direct role-mirror of `refinement_orchestrator/acceptance_floor.py`'s
"worst-case wins" deterministic classifier (its file header L1-22 is the
convention this one follows).

Reject-ceiling rule (D-05): any lens REJECT -> panel REJECT; else any REFINE ->
panel REFINE (union the RefinementTarget[]); ACCEPT iff ALL lenses ACCEPT. Critics
hold ONLY the reject/veto ceiling (05) — the aggregate is a verdict, it never
holds `approve` and never rewrites the assessment (transformation-pure). The panel
cannot be talked into ACCEPT by four ACCEPTs if the fifth REJECTs.

Field policy for the aggregate CriticVerdict (Pitfall 6 — every required field
populated so construction never `ValidationError`s):
  * `loaded_skills=[]`               — deterministic; no skills loaded (D-02).
  * `failure_modes`                  — union of the DRIVING lenses' failure_modes
                                       (the lenses whose verdict == the panel
                                       label; empty on ACCEPT).
  * `refinement_targets`             — union of the DRIVING lenses' targets
                                       (empty on ACCEPT).
  * `confidence`                     — MIN over the driving lenses (the strictest
                                       lens's confidence anchors the panel; on
                                       all-ACCEPT it is the min over all five —
                                       the least-confident approval).
  * `registry_snapshot_hash`         — sha256 over the member verdicts' hashes in
                                       stable order (reproducible provenance).
  * `source_critic_verdict_id`       — deterministic id derived from the same
                                       member hash.
"""
from __future__ import annotations

import hashlib

from core.contracts.schemas import CriticVerdict

# Strictest-first ordering — the reject ceiling (index 0 dominates).
_PRECEDENCE = ("REJECT", "REFINE", "ACCEPT")


def aggregate_panel(verdicts: list[CriticVerdict]) -> CriticVerdict:
    """Reduce the per-lens `CriticVerdict`s to ONE panel verdict (reject-ceiling).

    Pure: same inputs always produce the same output; no side effects, no IO.

    Args:
        verdicts: the per-lens `CriticVerdict`s (typically the five lenses). Must
            be non-empty — an empty list is a programming error (clear raise, not
            a silent ACCEPT stub).

    Returns:
        One aggregate `CriticVerdict`: `verdict` is the strictest lens label
        (REJECT > REFINE > ACCEPT); `refinement_targets`/`failure_modes` are the
        union over the driving lenses; every required field populated.

    Raises:
        ValueError: if `verdicts` is empty.
    """
    if not verdicts:
        raise ValueError(
            "aggregate_panel requires at least one CriticVerdict; got an empty list "
            "(the panel runner must fan at least one lens — no silent ACCEPT stub)."
        )

    labels = {v.verdict for v in verdicts}
    panel_label = next(label for label in _PRECEDENCE if label in labels)

    # Driving lenses = those whose verdict equals the panel label. On ACCEPT there
    # is no non-ACCEPT driver, so the "drivers" for the confidence floor are all
    # five (the least-confident approval anchors the panel).
    driving = [v for v in verdicts if v.verdict == panel_label]
    confidence_pool = driving if panel_label != "ACCEPT" else verdicts

    # Union the driving lenses' targets + failure modes (ACCEPT drivers carry none).
    targets = [t for v in driving for t in v.refinement_targets]
    failure_modes = sorted({fm for v in driving for fm in v.failure_modes})

    confidence = min(v.confidence for v in confidence_pool)

    snapshot_hash = _aggregate_hash(verdicts)
    verdict_id = f"scv-panel-{snapshot_hash[:16]}"

    rationale = _aggregate_rationale(panel_label, verdicts, driving)

    return CriticVerdict(
        verdict=panel_label,
        confidence=confidence,
        refinement_targets=targets,
        failure_modes=failure_modes,
        rationale=rationale,
        loaded_skills=[],  # deterministic — no skills loaded (D-02)
        source_critic_verdict_id=verdict_id,
        registry_snapshot_hash=snapshot_hash,
    )


def _aggregate_hash(verdicts: list[CriticVerdict]) -> str:
    """Reproducible provenance: sha256 over the member verdicts' hashes + labels.

    Order-stable: sorted by (registry_snapshot_hash, verdict, source id) so the
    same set of member verdicts always yields the same aggregate hash regardless
    of fan-out ordering.
    """
    members = sorted(
        f"{v.registry_snapshot_hash}|{v.verdict}|{v.source_critic_verdict_id or ''}"
        for v in verdicts
    )
    blob = "||".join(members)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _aggregate_rationale(
    panel_label: str,
    verdicts: list[CriticVerdict],
    driving: list[CriticVerdict],
) -> str:
    """A short, honest readout of how the reject-ceiling resolved."""
    counts = {label: sum(1 for v in verdicts if v.verdict == label) for label in _PRECEDENCE}
    tally = ", ".join(f"{counts[label]} {label}" for label in _PRECEDENCE)
    if panel_label == "ACCEPT":
        return f"panel ACCEPT — all {len(verdicts)} lenses accept ({tally})."
    return (
        f"panel {panel_label} (reject-ceiling) — driven by {len(driving)} "
        f"{panel_label} lens verdict(s) ({tally}); the strictest lens holds the ceiling."
    )


__all__ = ["aggregate_panel"]
