---
name: critique-discipline-auditor
description: >
  Auditor-variant critique discipline for trade_auditor_agent.
  Scopes critique to a single execution_id. Structures around
  Entry Assessment / Behavioral Signals / Execution Quality.
  Prevents cross-trade references and multi-execution pattern inference.
  Per-profile override of the base critique-discipline skill.
version: "1.0.0"
tags: [critique, auditor, phase-60, optional]
applies_to_profiles:
  - trade_auditor_agent
  - trade_auditor_agent._analyzer
---

# Critique Discipline (Auditor Variant)

## Scope

This skill governs trade_auditor_agent critique output. Every critique MUST:
- Scope to a single `execution_id` (never reference other executions)
- Structure output around: **Entry Assessment** / **Behavioral Signals** / **Execution Quality**
- Cite every assertion via `[ref:<registry_id>:<field>]` grammar (see citation-discipline)

## Invariants

1. **Single-execution scope**: Do not infer cross-trade patterns — that is behavioral_mentor_agent scope.
2. **No multi-execution aggregate stats** unless loaded from a registered tool result.
3. **No causality claims** (e.g., "Behavior X INCREASED AFTER event Y" is Phase 62 scope).

## Structure Template

```
**Entry Assessment**
[ref:regime_analysis_tool:regime_label] with [ref:liquidity_analysis_tool:liquidity_score] ...

**Behavioral Signals**
[ref:behavioral_analysis_tool:detected_patterns] observed on execution [execution_id] ...

**Execution Quality**
[ref:execution_quality_tool:overall_score] — [ref:execution_quality_tool:narrative] ...
```

## Anti-Patterns

- Do NOT reference other executions by ID
- Do NOT use phrases like "compared to your last 10 trades"
- Do NOT invent behavioral pattern IDs not in registry/behavioral_pattern/

## Registry References

- `[ref:behavioral_analysis_tool:*]` — single-execution behavioral signals
- `[ref:execution_quality_tool:*]` — execution quality score + narrative
- `[ref:regime_analysis_tool:*]` — market context
- `[ref:behavioral_pattern:<id>]` — pattern registry entries
