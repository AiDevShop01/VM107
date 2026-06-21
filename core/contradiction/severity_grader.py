"""Phase 89 Wave 3 — B13 severity grader.

Pure function: takes per-asset divergence sigma + active BeliefStore beliefs +
B13 contract YAML dict → returns SeverityResult.

No I/O. All rule parameters read from the contract dict so rules are data-driven.

Severity thresholds (per B13 contract §5.2):
  info:     single asset at 1.5–2.5σ
  warning:  single asset at 2.5–3.5σ  OR  ≥2 assets at 1.5–2.5σ same direction
  blocking: any asset >3.5σ  OR  contradicts BeliefStore belief at confidence >0.7

Per project locks:
  - Pure function — no env var reads, no DB calls.
  - Belief-trigger path checks active_beliefs list passed by caller.
  - Returns SeverityResult (dataclass) — not a plain dict.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ── Constants (per B13 contract) ─────────────────────────────────────────────

# Sigma thresholds
_INFO_LOWER = 1.5
_INFO_UPPER = 2.5
_WARN_LOWER = 2.5
_WARN_UPPER = 3.5
_BLOCK_LOWER = 3.5

# Belief-trigger: any belief with confidence > this fires blocking
_BELIEF_CONFIDENCE_THRESHOLD = 0.7


# ── Return type ───────────────────────────────────────────────────────────────

@dataclass
class SeverityResult:
    """Result from grade_severity().

    Attributes:
        severity: "info" | "warning" | "blocking"
        triggers_fired: Which specific rule paths fired (for audit trail).
        ui_surface: "none" | "indicator_page_banner" | "indicator_page_banner_red"
        downstream_confidence_delta: 0.0 | -0.20 | "REFUSE_CONFIDENT_EMIT"
    """

    severity: str
    triggers_fired: list[str] = field(default_factory=list)
    ui_surface: str = "none"
    downstream_confidence_delta: float | str = 0.0


# ── Core grading logic ────────────────────────────────────────────────────────

def grade_severity(
    divergence_sigma_per_asset: dict[str, float],
    active_beliefs: list[dict],
    contract: dict,
) -> SeverityResult:
    """Grade B13 severity from per-asset sigma values + active beliefs.

    Args:
        divergence_sigma_per_asset: {asset_id: sigma_float} — pre-computed divergences.
        active_beliefs: List of BeliefStore belief dicts that apply to this indicator.
                        Each must have 'confidence' key. Empty list if no relevant beliefs.
        contract: Full parsed dict from contract.b13_contradiction_engine.yaml.

    Returns:
        SeverityResult with severity, triggers_fired, ui_surface,
        downstream_confidence_delta.
    """
    triggers_fired: list[str] = []

    # ── Check 1: Blocking by high-sigma threshold ─────────────────────────
    high_sigma_assets = [
        asset for asset, sigma in divergence_sigma_per_asset.items()
        if sigma > _BLOCK_LOWER
    ]
    if high_sigma_assets:
        for asset in high_sigma_assets:
            triggers_fired.append(
                f"single_asset_divergence_sigma > {_BLOCK_LOWER}: {asset}={divergence_sigma_per_asset[asset]:.2f}σ"
            )
        return SeverityResult(
            severity="blocking",
            triggers_fired=triggers_fired,
            ui_surface="indicator_page_banner_red",
            downstream_confidence_delta="REFUSE_CONFIDENT_EMIT",
        )

    # ── Check 2: Blocking by high-confidence belief contradiction ─────────
    # Gold contradicting a CPI→Gold belief when actual direction reversed
    high_conf_beliefs = [
        b for b in active_beliefs
        if b.get("confidence", 0.0) > _BELIEF_CONFIDENCE_THRESHOLD
    ]
    if high_conf_beliefs:
        # At least one asset must show a divergence (>0σ) — we have a contradiction
        # if any prediction was directionally wrong against an active high-conf belief
        diverging_assets = [
            asset for asset, sigma in divergence_sigma_per_asset.items()
            if sigma > 0.0
        ]
        if diverging_assets:
            for b in high_conf_beliefs:
                triggers_fired.append(
                    f"contradicts_beliefstore_belief_confidence > {_BELIEF_CONFIDENCE_THRESHOLD}: "
                    f"belief_id={b.get('belief_id', 'unknown')} conf={b['confidence']}"
                )
            return SeverityResult(
                severity="blocking",
                triggers_fired=triggers_fired,
                ui_surface="indicator_page_banner_red",
                downstream_confidence_delta="REFUSE_CONFIDENT_EMIT",
            )

    # ── Check 3: Warning by single-asset high-sigma ───────────────────────
    warn_single_assets = [
        asset for asset, sigma in divergence_sigma_per_asset.items()
        if _WARN_LOWER <= sigma <= _WARN_UPPER
    ]
    if warn_single_assets:
        for asset in warn_single_assets:
            triggers_fired.append(
                f"single_asset_divergence_sigma [{_WARN_LOWER}, {_WARN_UPPER}]: "
                f"{asset}={divergence_sigma_per_asset[asset]:.2f}σ"
            )
        return SeverityResult(
            severity="warning",
            triggers_fired=triggers_fired,
            ui_surface="indicator_page_banner",
            downstream_confidence_delta=-0.20,
        )

    # ── Check 4: Warning by multi-asset same-direction divergence ─────────
    # ≥2 assets in the info band (1.5–2.5σ) simultaneously — indicates
    # coordinated broad-based surprise; qualifies as "same direction"
    multi_asset_info = [
        asset for asset, sigma in divergence_sigma_per_asset.items()
        if _INFO_LOWER <= sigma <= _INFO_UPPER
    ]
    if len(multi_asset_info) >= 2:
        for asset in multi_asset_info:
            triggers_fired.append(
                f"multi_asset_same_direction_sigma [{_INFO_LOWER}, {_INFO_UPPER}]: "
                f"{asset}={divergence_sigma_per_asset[asset]:.2f}σ"
            )
        return SeverityResult(
            severity="warning",
            triggers_fired=triggers_fired,
            ui_surface="indicator_page_banner",
            downstream_confidence_delta=-0.20,
        )

    # ── Check 5: Info (single-asset in 1.5–2.5σ band) ────────────────────
    info_assets = [
        asset for asset, sigma in divergence_sigma_per_asset.items()
        if _INFO_LOWER <= sigma <= _INFO_UPPER
    ]
    if info_assets:
        for asset in info_assets:
            triggers_fired.append(
                f"single_asset_divergence_sigma [{_INFO_LOWER}, {_INFO_UPPER}]: "
                f"{asset}={divergence_sigma_per_asset[asset]:.2f}σ"
            )
        return SeverityResult(
            severity="info",
            triggers_fired=triggers_fired,
            ui_surface="none",
            downstream_confidence_delta=0.0,
        )

    # ── Fallback: below all thresholds (<1.5σ on all assets) ─────────────
    # Not enough divergence to classify — return info with no triggers
    return SeverityResult(
        severity="info",
        triggers_fired=["below_threshold"],
        ui_surface="none",
        downstream_confidence_delta=0.0,
    )
