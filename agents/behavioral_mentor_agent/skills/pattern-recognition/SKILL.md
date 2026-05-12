---
name: pattern-recognition
description: >
  Behavioral variant of pattern recognition for behavioral_mentor_agent. Identifies
  recurring behavioral patterns ACROSS multiple trades for ONE account using Phase 58
  V1 pattern vocabulary. Citation grammar uses [ref:behavioral_pattern:<id>] and
  [ref:get_cross_trade_behavioral_patterns:<field>]. Anti-patterns: do not invent
  new patterns; do not assert Behavior-INCREASES_AFTER-Outcome (Phase 62).
version: "1.0.0"
tags: [pattern-recognition, cross-trade, behavioral, account-scoped, phase-60]
trigger_patterns:
  - "recognize behavioral patterns"
  - "identify cross-trade patterns"
  - "detect pattern frequency"
  - "behavioral pattern analysis"
allowed_tools:
  - skills_tool
---

# Pattern Recognition (Behavioral Cross-Trade Variant)

## Scope Invariant

**Cross-trade pattern recognition for ONE account.** You may identify behavioral
patterns that appear recurrently across the account's execution history. You may
NOT make single-execution pattern observations as the primary unit of critique.

Single-execution pattern detection is `trade_auditor_agent`'s scope.
Cross-account pattern comparison is Phase 62's scope.
Causal edge inference (`Behavior-INCREASES_AFTER-Outcome`) is Phase 62's scope.

## Phase 58 V1 Behavioral Pattern Registry

Use ONLY patterns from this V1 registry. Always cite via `[ref:behavioral_pattern:<id>]`:

| Pattern ID | Registry Ref | Trigger Condition |
|------------|--------------|-------------------|
| `hesitation` | `[ref:behavioral_pattern:hesitation]` | Entry delay > 3 seconds after signal |
| `fomo` | `[ref:behavioral_pattern:fomo]` | Entry after price moved > 0.3% past signal zone |
| `late_entry` | `[ref:behavioral_pattern:late_entry]` | Entry > 5 bars after ideal entry bar |
| `revenge` | `[ref:behavioral_pattern:revenge]` | Entry within 15 min of prior losing trade, same symbol |
| `oversize` | `[ref:behavioral_pattern:oversize]` | Position size > 2x account-risk-adjusted standard |

**Do NOT use patterns outside this V1 registry.** Unknown registry IDs hard-fail
citation validation. Phase 60 uses the V1 vocabulary only.

## Citation Grammar

For cross-trade patterns from `get_cross_trade_behavioral_patterns`:

```
[ref:behavioral_pattern:hesitation]                               # pattern registry entry
[ref:get_cross_trade_behavioral_patterns:pattern_frequency_pct]   # frequency field
[ref:get_cross_trade_behavioral_patterns:pattern_cluster_after_loss]  # clustering field
[ref:get_cross_trade_behavioral_patterns:pattern_trend]           # evolution field
```

Both the PATTERN and the FREQUENCY/CLUSTER FIELD should be cited when both are available.

## Recognition Protocol

1. Check `AnalyzerOutput.behavioral_signals` — what patterns appear in the account history?
2. For each detected pattern (frequency > 10%), cite BOTH the pattern registry ID AND
   the frequency/cluster evidence field from `get_cross_trade_behavioral_patterns`.
3. If a pattern was NOT detected at threshold frequency, do NOT mention it.
4. If NO behavioral patterns were detected above threshold, emit one TRANSITION:
   "No recurring behavioral patterns were detected above threshold for this account."

## Clustering Recognition

Cross-trade pattern recognition includes identifying when patterns cluster:
- **After-loss clustering:** revenge_trade appearing disproportionately after losses
  → cite `[ref:get_cross_trade_behavioral_patterns:pattern_cluster_after_loss]`
- **Setup-type clustering:** hesitation appearing predominantly in A+ setup types
  → cite `[ref:get_cross_trade_behavioral_patterns:pattern_cluster_by_setup_type]`
- **Co-occurrence:** fomo + late_entry appearing together in the same executions
  → cite `[ref:get_cross_trade_behavioral_patterns:pattern_cooccurrence]`

## Anti-Patterns

- **Do NOT generalize patterns as "always"** — cite the frequency percentage.
- **Do NOT invent new pattern IDs** — only V1 registry patterns are citable.
- **Do NOT assert causality** — patterns are observational. "Hesitation correlates
  with..." is acceptable; "Hesitation CAUSES..." is Phase 62 scope.
- **Do NOT confuse signal with pattern** — the price signal is not the behavioral
  pattern. Cite `behavioral_pattern:<id>`, not `replay_line:<id>` or `signal:<id>`.
- **Do NOT reference prior narratives** — `narrative_visibility=NONE`. No "as
  previously noted" references.
