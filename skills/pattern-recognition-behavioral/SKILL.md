---
name: pattern-recognition-behavioral
description: >
  Cross-trade behavioral pattern recognition skill for behavioral_mentor_agent.
  Identifies recurring Phase 58 V1 behavioral patterns ACROSS multiple executions
  for ONE account. Citation grammar uses [ref:behavioral_pattern:<id>] and
  [ref:get_cross_trade_behavioral_patterns:<field>].
  Strictly prohibits causality claims.
version: "1.0.0"
tags: [pattern-recognition, behavioral, cross-trade, phase-60]
applies_to_profiles:
  - behavioral_mentor_agent
  - behavioral_mentor_agent._reader
  - behavioral_mentor_agent._analyzer
---

# Pattern Recognition (Behavioral Variant)

## Scope

Cross-trade behavioral pattern recognition for behavioral_mentor_agent.
Scope: ONE account, MULTIPLE executions, Phase 58 V1 behavioral patterns.

## Registered Pattern IDs (Phase 58 V1)

Use ONLY these registry IDs in citations:
- `behavioral_pattern:fomo_entry` — entering trades impulsively on fear-of-missing-out
- `behavioral_pattern:hesitation` — delayed entry after setup confirmation
- `behavioral_pattern:late_entry` — entering after optimal window has closed
- `behavioral_pattern:over_management` — excessive position adjustment post-entry
- `behavioral_pattern:revenge_trade` — trading reactively after a loss

## Citation Grammar

Always cite pattern claims via `[ref:behavioral_pattern:<id>:<field>]`:
- `[ref:behavioral_pattern:fomo_entry:description]`
- `[ref:get_cross_trade_behavioral_patterns:rate]`
- `[ref:get_behavioral_edges:edges]`

## Pattern Identification Rules

1. **Minimum evidence**: At least 2 executions must exhibit the pattern before citing it.
2. **Rate bounds**: Only cite patterns with `rate >= 0.2` (20%+ of executions).
3. **No causality**: Do not assert "Pattern X CAUSES outcome Y" (Phase 62 scope).
4. **No new pattern IDs**: Do not invent pattern identifiers not in registry/behavioral_pattern/.

## Anti-Patterns

- "You tend to [pattern] when [emotional state]" — causality claim
- "Your performance would improve if you fixed [pattern]" — causal recommendation
- Using non-registry pattern names ("second-guessing", "over-trading", etc.)

## Tool Sequence

```
1. get_cross_trade_behavioral_patterns → pattern frequencies
2. get_behavioral_edges → behavioral clustering
3. get_behavioral_evolution_tool → longitudinal trends
```
