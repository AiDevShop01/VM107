---
name: pattern-recognition
description: >
  Weekly-variant pattern recognition for weekly_review_agent. Identifies behavioral
  and regime patterns at week scale: regime distribution across the week, instrument
  concentration, behavioral evolution across the week's executions. Citation grammar
  uses [ref:behavioral_pattern:<id>], [ref:get_weekly_execution_summary:*], and
  [ref:get_regime_context:*]. Anti-patterns: do not invent new pattern IDs; do not
  assert Behavior-INCREASES_AFTER-Outcome (Phase 62).
version: "1.0.0"
tags: [pattern-recognition, weekly, week-window, regime, behavioral, phase-60]
trigger_patterns:
  - "recognize week patterns"
  - "identify weekly behavioral patterns"
  - "detect regime distribution"
  - "week-scale pattern analysis"
  - "behavioral evolution weekly"
allowed_tools:
  - skills_tool
---

# Pattern Recognition (Weekly Variant)

## Scope Invariant

**Week-scale pattern recognition for ONE account within a canonical week window.**
You may identify:
1. Behavioral patterns appearing across the week's executions (same V1 registry)
2. Regime distribution patterns (was the account's week concentrated in trending/ranging?)
3. Behavioral evolution at week scale (is hesitation frequency this week different from
   prior data available?)
4. Instrument concentration patterns (was the week overexposed to one symbol?)

Single-execution pattern detection is `trade_auditor_agent`'s scope.
Cross-account pattern comparison is Phase 62's scope.
Causal edge inference is Phase 62's scope.
Prior narrative analysis is FORBIDDEN — `narrative_visibility=NONE`.

## Phase 58 V1 Behavioral Pattern Registry

Use ONLY patterns from the V1 registry. Always cite via `[ref:behavioral_pattern:<id>]`:

| Pattern ID | Registry Ref | Trigger Condition |
|------------|--------------|-------------------|
| `hesitation` | `[ref:behavioral_pattern:hesitation]` | Entry delay > 3 seconds after signal |
| `fomo` | `[ref:behavioral_pattern:fomo]` | Entry after price moved > 0.3% past signal zone |
| `late_entry` | `[ref:behavioral_pattern:late_entry]` | Entry > 5 bars after ideal entry bar |
| `revenge` | `[ref:behavioral_pattern:revenge]` | Entry within 15 min of prior losing trade, same symbol |
| `oversize` | `[ref:behavioral_pattern:oversize]` | Position size > 2x account-risk-adjusted standard |

**Do NOT use patterns outside this V1 registry.** Unknown registry IDs hard-fail citation validation.

## Week-Scale Citation Grammar

For behavioral patterns at week frequency:
```
[ref:behavioral_pattern:hesitation]                           # pattern registry entry
[ref:behavioral_analysis_tool:hesitation_seconds]             # evidence field per execution
[ref:get_weekly_execution_summary:executions]                 # week-window execution list
```

For regime patterns:
```
[ref:get_regime_context:regime_class]                         # trending/ranging/volatile
[ref:get_regime_context:volatility_rank]                      # volatility classification
```

For portfolio concentration:
```
[ref:get_weekly_execution_summary:executions]                 # source of instrument distribution
```

For performance outcomes:
```
[ref:get_performance_history:win_rate_pct]
[ref:get_performance_history:max_drawdown_pct]
[ref:get_performance_history:avg_quality_score]
```

Both the PATTERN and the FREQUENCY EVIDENCE FIELD should be cited when both are available.

## Week-Scale Recognition Protocol

1. Check `AnalyzerOutput.behavioral_signals` — what patterns appeared this week? At what frequency?
2. For each detected pattern (frequency > 10%), cite BOTH:
   - The pattern registry ID: `[ref:behavioral_pattern:<id>]`
   - The evidence field: `[ref:behavioral_analysis_tool:<field>]`
3. Check `AnalyzerOutput.findings.portfolio.regime_distribution` — was the week
   concentrated in one regime? Cite: `[ref:get_regime_context:regime_class]`
4. Check `AnalyzerOutput.findings.portfolio.instrument_concentration_pct` — was the week
   overexposed to one instrument? Cite: `[ref:get_weekly_execution_summary:executions]`
5. Check `AnalyzerOutput.findings.mentor.pattern_trend` — are patterns improving or
   worsening at week scale? If data supports it, cite the trend evidence field.
6. If NO behavioral patterns detected above threshold, emit one TRANSITION:
   "No recurring behavioral patterns were detected above threshold this week."

## Regime Distribution Recognition

Week-scale pattern recognition includes identifying regime concentration:

- **Trending-regime concentration:** >70% of week's executions in trending regime
  → cite `[ref:get_regime_context:regime_class]`
- **Ranging-regime concentration:** >70% in ranging conditions
  → cite `[ref:get_regime_context:regime_class]`
- **Cross-regime execution:** executions spread across multiple regime types
  → this is typically positive (diversified conditions); note it

## Behavioral Evolution at Week Scale

When `AnalyzerOutput.findings.mentor.pattern_trend` is populated:
- `stable` → neutral observation (pattern persists at similar frequency)
- `improving` → ASSERTION with evidence: "hesitation frequency declined this week
  [ref:behavioral_pattern:hesitation][ref:behavioral_analysis_tool:hesitation_seconds]"
- `worsening` → ASSERTION with evidence + mentor note

**Only assert evolution if the analyzer data supports it.** Do NOT infer trends from
a single week without baseline data.

## Anti-Patterns

- **Do NOT generalize patterns as "always"** — cite the frequency percentage.
- **Do NOT invent new pattern IDs** — only V1 registry patterns are citable.
- **Do NOT assert causality** — patterns are observational. Phase 62 owns causal edges.
- **Do NOT reference prior narratives** — `narrative_visibility=NONE`. No "as previous
  weeks showed" or "per last week's review" references.
- **Do NOT use relative week offsets** — "last 7 days" → use canonical week_start/week_end.
- **Do NOT confuse signal with pattern** — the entry signal is not the behavioral pattern.
  Cite `behavioral_pattern:<id>`, not `signal:<id>`.
