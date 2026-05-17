---
name: pattern-recognition-weekly
description: >
  Weekly-variant pattern recognition for weekly_review_agent.
  Identifies behavioral and regime patterns at week scale: behavioral pattern
  frequency across the week's executions, regime distribution (trending vs. ranging),
  instrument concentration, and behavioral evolution at week scale.
  Citation grammar uses [ref:behavioral_pattern:<id>], [ref:get_weekly_execution_summary:*],
  and [ref:behavioral_analysis_tool:*].
version: "1.0.0"
tags: [pattern-recognition, weekly, cross-trade, regime, phase-60]
applies_to_profiles:
  - weekly_review_agent
  - weekly_review_agent._reader
  - weekly_review_agent._analyzer
---

# Pattern Recognition (Weekly Review Variant)

## Scope

Week-scale pattern recognition for weekly_review_agent.
Scope: ONE canonical week window, all executions within that window, cross-cutting regime + behavioral patterns.

## Pattern Categories for Week Review

### Behavioral Patterns (Phase 58 V1)
- `behavioral_pattern:fomo_entry` — week-level frequency
- `behavioral_pattern:hesitation` — week-level frequency
- `behavioral_pattern:late_entry` — week-level frequency
- `behavioral_pattern:over_management` — week-level frequency
- `behavioral_pattern:revenge_trade` — week-level frequency

### Regime Patterns
- Trending concentration (>60% trending sessions): Note alignment/misalignment
- Range-bound concentration (>60% range sessions): Note regime-appropriate setups
- Mixed regime: Note adaptability

### Behavioral Evolution (week-over-week)
- Reference `[ref:get_behavioral_evolution_tool:*]` for longitudinal context
- Only comment on week-over-week if previous week data is in tool result

## Citation Grammar

```
[ref:get_weekly_execution_summary:*]
[ref:get_cross_trade_behavioral_patterns:*]
[ref:behavioral_pattern:<id>:description]
[ref:get_behavioral_evolution_tool:trend_slope]
[ref:get_drift_report_tool:*]
```

## Pattern Identification Rules

1. **Week-temporal scope**: Only patterns from this week's execution cohort.
2. **Minimum frequency**: Cite behavioral patterns appearing in ≥2 executions.
3. **Evidence-bound**: Every pattern claim must trace to a tool result.
4. **No causality**: "Pattern X INCREASES AFTER event Y" is Phase 62 scope.
5. **No new pattern IDs**: Do not invent identifiers not in registry/behavioral_pattern/.

## Anti-Patterns

- Referencing executions from prior weeks (unless in tool result as comparison)
- Asserting causality between patterns and outcomes
- Using non-registry pattern names
- Inferring population-level patterns ("most traders with this pattern...")

## Tool Sequence

```
1. get_weekly_execution_summary → week overview
2. get_cross_trade_behavioral_patterns → behavioral pattern frequencies
3. get_behavioral_evolution_tool → week-over-week behavioral evolution
4. get_drift_report_tool → strategy drift signals for the week
```
