---
name: trend-continuation-critic
description: >
  Trend-continuation-strategy refinement critique discipline. Penalizes
  whipsaw sensitivity, late entries, tight ATR-stop fragility in trending
  regimes, and pyramid-style exposure without protective exits. Loaded by
  strategy_refinement_critic when
  StrategySpec.strategy_family == TREND_CONTINUATION.
version: "1.0.0"
tags:
  - critique
  - refinement
  - trend-continuation
  - phase-48
trigger_patterns:
  - evaluate trend strategy
  - critique trend continuation
  - score trend follow
  - refine trend system
allowed_tools:
  - skills_tool
  - lookup_capability
  - search_knowledge
  - document_query
  - response
applies_to_profiles:
  - strategy_refinement_critic
---

# Trend-Continuation Critic — Family Overlay

## Family-Specific Evaluation Heuristics

When the StrategySpec family is TREND_CONTINUATION, weight these robustness signals heavily:

- **Whipsaw sensitivity:** trend systems that lose more than they earn during pullbacks have entry filters too eager. Check `consecutive_losses` — a number near the veto floor (10) signals whipsaw exposure even if the headline metrics pass.
- **Late entry penalty:** entries triggered late in the trend (after >70% of the move) carry asymmetric tail risk. Look for entry rules conditioned only on confirmation (e.g., 200-EMA already retraced) without an early-trend filter.
- **ATR-stop fragility:** stops tighter than 2x ATR in TREND_CONTINUATION systems get clipped by normal counter-trend retracements. Stops wider than 4x ATR destroy reward/risk. Flag both extremes.
- **Pullback-entry discipline:** strong trend systems enter on pullbacks WITH confirmation (price respects the trend filter on the retest), not on every breakout of a moving-average crossing. Look at StrategySpec.rules for the pullback-confirmation pattern.
- **Trend-strength gate:** explicit ADX / slope / regression-residual gate prevents firing during chop. Absence is a refinement opportunity.
- **Exit logic:** trail-stop exits dominate fixed-target exits in trend systems. A static profit target on a trend strategy almost always under-performs.

## Family-Specific Refinement Targets

When emitting `RefinementTarget` objects for a trend-continuation strategy, prefer these `target_field` choices:

- `target_field: "features.trend_strength_filter"` — add or tighten ADX / slope gate.
- `target_field: "rules.pullback_confirmation"` — require an explicit pullback-and-resume pattern.
- `target_field: "rules.stop_geometry"` — recalibrate ATR multiplier within the 2x-4x band.
- `target_field: "rules.exit_logic"` — switch fixed target to trail-stop or chandelier exit.
- `target_field: "features.regime_filter"` — restrict to identified trending regimes only.

Each target should pair a `canonical_issue_id` (e.g., `fm_whipsaw_sensitivity`, `fm_late_entry`, `fm_stop_geometry_fragile`) with the structural change.
