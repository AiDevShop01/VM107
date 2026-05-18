---
name: breakout-critic
description: >
  Breakout-strategy refinement critique discipline. Penalizes overfit
  breakout thresholds, false-breakout sensitivity, single-regime
  concentration, and weak post-breakout confirmation logic. Loaded by
  strategy_refinement_critic when StrategySpec.strategy_family == BREAKOUT.
version: "1.0.0"
tags:
  - critique
  - refinement
  - breakout
  - phase-48
trigger_patterns:
  - evaluate breakout strategy
  - critique breakout
  - score breakout
  - refine breakout
allowed_tools:
  - skills_tool
  - lookup_capability
  - search_knowledge
  - document_query
  - response
applies_to_profiles:
  - strategy_refinement_critic
---

# Breakout Critic — Family Overlay

## Family-Specific Evaluation Heuristics

When the StrategySpec family is BREAKOUT, weight these robustness signals heavily:

- **Threshold sensitivity:** if a small perturbation to the breakout buffer (ATR multiplier, range %, prior-high lookback) collapses expectancy, that is HIGH fragility. Penalize.
- **False-breakout rate:** examine `metrics.win_rate` in combination with `metrics.rr`. A breakout system with win_rate >= 0.45 and rr >= 1.8 can survive; win_rate < 0.40 with rr < 1.5 is brittle even if profit_factor barely clears the floor.
- **Single-regime concentration:** breakouts that only fire in one volatility regime (`regime_coverage` < 0.4) are typically overfit to a narrow expansion window. Penalize even when other metrics pass.
- **Confirmation logic class:** breakouts without a confirmation rule (volume surge, momentum follow-through, or session alignment) are weaker than those with explicit confirmation. Look at StrategySpec.rules for the presence of a confirmation pattern.
- **Stop-placement geometry:** stops too tight relative to range (sub-1.0 ATR) cause whipsaw losses; too loose (> 3.0 ATR) destroy reward/risk. Flag both.
- **Time-of-day filter:** session-aware breakouts outperform 24-hour ones in most asset classes. Absence of a session filter on liquid majors is a refinement opportunity.

## Family-Specific Refinement Targets

When emitting `RefinementTarget` objects for a breakout strategy, prefer these `target_field` choices:

- `target_field: "rules.breakout_threshold"` — adjust ATR multiplier or range filter.
- `target_field: "rules.confirmation_logic"` — add or strengthen post-break confirmation.
- `target_field: "rules.stop_geometry"` — recalibrate stop relative to volatility.
- `target_field: "features.regime_filter"` — restrict signal to compatible volatility regimes.
- `target_field: "rules.session_filter"` — add session-of-day gating.

Each target should pair a `canonical_issue_id` (e.g., `fm_overfit_breakout_threshold`, `fm_false_breakout_sensitivity`, `fm_regime_concentration`) with the structural change. Surgical, not wholesale.
