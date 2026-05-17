---
name: pattern-recognition-trade-auditor
description: >
  Single-trade behavioral pattern recognition skill for trade_auditor_agent.
  Identifies Phase 58 V1 behavioral patterns within ONE execution using
  registry citation grammar. Strictly prohibits cross-trade pattern inference
  (that scope belongs to behavioral_mentor_agent).
version: "1.0.0"
tags: [pattern-recognition, auditor, single-trade, phase-60]
applies_to_profiles:
  - trade_auditor_agent
  - trade_auditor_agent._reader
  - trade_auditor_agent._analyzer
---

# Pattern Recognition (Trade Auditor Variant)

## Scope

Single-trade behavioral pattern recognition for trade_auditor_agent.
Scope: ONE execution, Phase 58 V1 behavioral patterns detected within that execution.

## Registered Pattern IDs (Phase 58 V1)

Use ONLY these registry IDs in citations:
- `behavioral_pattern:fomo_entry` — entering trades impulsively on fear-of-missing-out
- `behavioral_pattern:hesitation` — delayed entry after setup confirmation
- `behavioral_pattern:late_entry` — entering after optimal window has closed
- `behavioral_pattern:over_management` — excessive position adjustment post-entry
- `behavioral_pattern:revenge_trade` — trading reactively after a loss

## Citation Grammar

Always cite pattern detections via `[ref:behavioral_pattern:<id>:<field>]`:
- `[ref:behavioral_pattern:fomo_entry:description]`
- `[ref:behavioral_analysis_tool:detected_patterns]`

## Pattern Identification Rules

1. **Single-execution scope**: Only cite patterns detectable from this execution's data.
2. **Evidence-bound**: Must have evidence from `behavioral_analysis_tool` results.
3. **No cross-trade reference**: Do not reference other executions.
4. **No causality**: Do not assert "Pattern X CAUSES outcome Y".
5. **No new pattern IDs**: Do not invent identifiers not in registry/behavioral_pattern/.

## Anti-Patterns

- "You often do this" — cross-trade inference
- "In your last 5 trades, you showed..." — cross-trade scope
- Using non-registry pattern names

## Tool Sequence

```
1. behavioral_analysis_tool → detected patterns for this execution
```
