---
name: mean-reversion-critic
description: >
  Mean-reversion-strategy refinement critique discipline. Penalizes
  trend-regime concentration, weak reversion confirmation, overfit to
  range-bound segments, and exit logic that catches the knife.
  Loaded by strategy_refinement_critic when
  StrategySpec.strategy_family == MEAN_REVERSION.
version: "1.0.0"
tags:
  - critique
  - refinement
  - mean-reversion
  - phase-48
trigger_patterns:
  - evaluate mean reversion strategy
  - critique mean reversion
  - score reversion
  - refine reversion
allowed_tools:
  - skills_tool
  - lookup_capability
  - search_knowledge
  - document_query
  - response
applies_to_profiles:
  - strategy_refinement_critic
---

# Mean-Reversion Critic — Family Overlay

## Family-Specific Evaluation Heuristics

When the StrategySpec family is MEAN_REVERSION, weight these robustness signals heavily:

- **Trend-regime concentration:** mean-reversion that backtests well only in low-trend regimes (`regime_coverage` skewed) is fragile. If the regime coverage is concentrated on a single low-ADX or low-trend bucket, penalize.
- **Range-bound overfit:** a system whose expectancy depends on a specific historical range-bound segment (instead of a regime descriptor that generalises) is overfit. Look for parameter values that imply a known range from the training period.
- **Reversion confirmation:** entries should require a confirmation that the move is exhausted (RSI divergence, volume drying up, prior support test, range mean re-touch). Naked entries on a Bollinger touch without confirmation are brittle.
- **Catch-the-knife exits:** mean-reversion exits that target the mean without a hard stop above/below the prior extreme are catastrophic in trending regimes. The exit logic must include an explicit "this is not reverting" abort.
- **Win-rate vs reward-risk balance:** mean-reversion typically runs `win_rate >= 0.55` with `rr` between 0.8 and 1.5. A spec with `win_rate < 0.50` and `rr < 1.2` is almost certainly catching breakouts, not reverting.
- **Sample-size sensitivity:** mean-reversion needs many trades for statistical confidence — a `sample_size` near the floor (200-300) with high reported `profit_factor` is suspicious; flag as overfit risk.

## Family-Specific Refinement Targets

When emitting `RefinementTarget` objects for a mean-reversion strategy, prefer these `target_field` choices:

- `target_field: "rules.confirmation_logic"` — require divergence, volume signature, or prior-level test before entry.
- `target_field: "rules.exit_geometry"` — add a hard abort stop beyond the prior extreme.
- `target_field: "features.regime_filter"` — restrict to low-trend / range-classified regimes only.
- `target_field: "rules.entry_threshold"` — recalibrate the over-extension trigger (e.g., RSI 30/70 vs 25/75) for the current regime.
- `target_field: "features.volatility_filter"` — gate by volatility band so the system stops firing in expansion regimes.

Each target should carry a `canonical_issue_id` from the locked taxonomy (e.g., `fm_regime_concentration`, `fm_overfit_range_bound`, `fm_weak_reversion_confirmation`).
