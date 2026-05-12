---
name: pattern-recognition
description: >
  Single-trade behavioral pattern recognition for trade_auditor_agent. Identifies
  known Phase 58 V1 behavioral patterns within ONE execution. Uses registry IDs
  for citation. Strictly prohibits cross-trade pattern inference.
version: "1.0.0"
tags: [pattern-recognition, single-execution, behavioral, phase-60]
trigger_patterns:
  - "recognize pattern"
  - "identify behavior"
  - "detect hesitation"
  - "check behavioral signals"
allowed_tools:
  - skills_tool
---

# Pattern Recognition (Single-Trade Variant)

## Scope Invariant

**Single-execution pattern recognition only.** You may identify behavioral
patterns that fired during this specific execution. You may NOT infer cross-trade
trends from one data point.

Cross-trade behavioral pattern analysis (e.g., "this trader hesitates on 70% of
breakout entries") is `behavioral_mentor_agent`'s scope, not yours.

## Phase 58 V1 Behavioral Pattern Registry

Recognize these known patterns. Always cite via `[ref:behavioral_pattern:<id>]`:

| Pattern ID | Registry Ref | Trigger Condition |
|------------|--------------|-------------------|
| `hesitation` | `[ref:behavioral_pattern:hesitation]` | Entry delay > 3 seconds after signal |
| `fomo` | `[ref:behavioral_pattern:fomo]` | Entry after price moved > 0.3% past signal zone |
| `late_entry` | `[ref:behavioral_pattern:late_entry]` | Entry > 5 bars after ideal entry bar |
| `revenge` | `[ref:behavioral_pattern:revenge]` | Entry within 15 min of prior losing trade, same symbol |
| `oversize` | `[ref:behavioral_pattern:oversize]` | Position size > 2x account-risk-adjusted standard |

## Citation Grammar

For behavioral patterns detected via `behavioral_analysis_tool`:

```
[ref:behavioral_pattern:hesitation]           # pattern registry entry
[ref:behavioral_analysis_tool:hesitation_seconds]  # specific evidence field
```

Both the PATTERN and the EVIDENCE FIELD should be cited when both are available.

## Recognition Protocol

1. Check `AnalyzerOutput.behavioral_signals` — what patterns were detected?
2. For each detected pattern, cite BOTH the pattern registry ID AND the
   evidence field from `behavioral_analysis_tool`.
3. If a pattern was NOT detected, do NOT mention it. Absence of evidence ≠ evidence
   of absence worth noting (unless the critique specifically requires it).
4. If zero behavioral patterns were detected, emit one TRANSITION:
   "No behavioral patterns were detected for this execution."

## Anti-Patterns

- **Do NOT generalize from one execution** — "this trader hesitates" requires
  cross-trade evidence from `behavioral_mentor_agent`.
- **Do NOT invent patterns** — only cite patterns from `AnalyzerOutput.behavioral_signals`.
- **Do NOT use unlisted patterns** — if a behavior isn't in the Phase 58 V1 registry
  above, it cannot be cited (unknown registry_id → hard-fail).
- **Do NOT confuse signal with pattern** — the signal (price level) is not the
  behavioral pattern. Cite `behavioral_pattern:<id>`, not `replay_line:<id>`.
