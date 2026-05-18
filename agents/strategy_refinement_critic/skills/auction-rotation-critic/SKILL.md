---
name: auction-rotation-critic
description: >
  Auction-rotation-strategy refinement critique discipline. Penalizes
  session-misaligned entries, weak rotation confirmation, false signals
  on rotation breakouts, and absence of value-area / POC discipline.
  Loaded by strategy_refinement_critic when
  StrategySpec.strategy_family == AUCTION_ROTATION.
version: "1.0.0"
tags:
  - critique
  - refinement
  - auction-rotation
  - phase-48
trigger_patterns:
  - evaluate auction rotation strategy
  - critique rotation
  - score auction
  - refine market-profile strategy
allowed_tools:
  - skills_tool
  - lookup_capability
  - search_knowledge
  - document_query
  - response
applies_to_profiles:
  - strategy_refinement_critic
---

# Auction-Rotation Critic — Family Overlay

## Family-Specific Evaluation Heuristics

When the StrategySpec family is AUCTION_ROTATION, weight these robustness signals heavily:

- **Session alignment:** auction-rotation patterns are session-specific (RTH vs ETH, futures session opens, FX session overlaps). Strategies that fire across all hours without a session gate are almost always overfit to one session in the backtest.
- **Rotation confirmation:** valid rotations require evidence of failed-auction at the prior extreme (poor high, poor low, single-print rejection). Naked entries on a value-area-edge touch lack confirmation.
- **False rotation-breakout signature:** if `win_rate` and `rr` look great but `consecutive_losses` is high, the system likely catches genuine breakouts as failed rotations. Inspect the exit and stop logic for this asymmetry.
- **Value-area / POC discipline:** entries should reference the prior session's developing value area, point-of-control, or balanced-vs-trend-day classification. Absence of these references in StrategySpec.features is a refinement target.
- **Day-type sensitivity:** rotation systems perform on balanced day-types and fail on trend day-types. A `regime_coverage` that is high but unsegmented by day-type is suspicious — flag the missing day-type classifier.
- **Profile-shape generalisation:** parameters tuned to one historical profile shape (e.g., normal-variation P-shape) and then applied universally is overfit; look for hardcoded thresholds that resemble specific historical sessions.

## Family-Specific Refinement Targets

When emitting `RefinementTarget` objects for an auction-rotation strategy, prefer these `target_field` choices:

- `target_field: "rules.session_filter"` — add explicit session-of-day / overlap window gating.
- `target_field: "rules.rotation_confirmation"` — require failed-auction signature at the extreme.
- `target_field: "features.day_type_classifier"` — add balanced-vs-trend-day filter.
- `target_field: "features.value_area_reference"` — gate entries to prior value area or POC.
- `target_field: "rules.stop_geometry"` — anchor stops to profile structure (single-prints, prior extremes) instead of fixed ATR.

Each target should pair a `canonical_issue_id` (e.g., `fm_session_misalignment`, `fm_weak_rotation_confirmation`, `fm_breakout_as_rotation`) with the structural change.
