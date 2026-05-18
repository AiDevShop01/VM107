---
name: volatility-expansion-critic
description: >
  Volatility-expansion-strategy refinement critique discipline. Penalizes
  stale volatility regime detection, late expansion entries, confusion
  between compression and expansion phases, and absence of an
  expansion-failure abort. Loaded by strategy_refinement_critic when
  StrategySpec.strategy_family == VOLATILITY_EXPANSION.
version: "1.0.0"
tags:
  - critique
  - refinement
  - volatility-expansion
  - phase-48
trigger_patterns:
  - evaluate volatility expansion strategy
  - critique expansion
  - score vol expansion
  - refine volatility breakout
allowed_tools:
  - skills_tool
  - lookup_capability
  - search_knowledge
  - document_query
  - response
applies_to_profiles:
  - strategy_refinement_critic
---

# Volatility-Expansion Critic — Family Overlay

## Family-Specific Evaluation Heuristics

When the StrategySpec family is VOLATILITY_EXPANSION, weight these robustness signals heavily:

- **Stale regime detection:** the system must detect compression FIRST (Bollinger squeeze, NR7, narrow-range cluster) before entering on expansion. Strategies that enter on absolute-vol-level alone, without the contraction precursor, are catching mid-expansion moves and miss the asymmetric edge.
- **Late expansion entry penalty:** entering after >50% of the expansion has already played out destroys reward/risk. Look for the entry trigger relative to the volatility-of-volatility signal (e.g., ATR_of_ATR delta) — late triggers underperform.
- **Compression-vs-expansion confusion:** if the same StrategySpec fires both during compression squeezes AND during ongoing expansion, the regime classifier is broken. Inspect rule conditions for ambiguity.
- **Expansion-failure abort:** when a triggered expansion fails (price re-enters the contraction range within N bars), the position must abort with a small loss. Absence of a re-entry abort produces large losers in failed setups.
- **Reward-risk asymmetry:** volatility expansion is the family with the strongest theoretical edge in `rr`. If `rr < 1.5` while `win_rate` is also modest, the spec is taking on directional risk without claiming the expansion premium — strong refinement signal.
- **Multi-timeframe alignment:** expansion on the trading timeframe should align with no immediate counter-expansion on the higher timeframe. Absence of an HTF alignment filter is a refinement opportunity.

## Family-Specific Refinement Targets

When emitting `RefinementTarget` objects for a volatility-expansion strategy, prefer these `target_field` choices:

- `target_field: "features.compression_detector"` — require an explicit pre-expansion compression signal.
- `target_field: "rules.expansion_trigger"` — define a precise volatility-of-volatility trigger.
- `target_field: "rules.failure_abort"` — add a re-entry-into-range abort condition.
- `target_field: "features.htf_alignment"` — gate signals by higher-timeframe direction.
- `target_field: "rules.profit_target"` — set targets relative to the contracted range projected, not fixed ATR multipliers.

Each target should pair a `canonical_issue_id` (e.g., `fm_stale_regime_detection`, `fm_late_expansion_entry`, `fm_compression_expansion_confusion`) with the structural change.
