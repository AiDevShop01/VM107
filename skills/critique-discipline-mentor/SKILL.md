---
name: critique-discipline-mentor
description: >
  Mentor-variant critique discipline for behavioral_mentor_agent.
  Scopes critique to CROSS-TRADE behavioral patterns for ONE account.
  Structures around Pattern Frequency / Behavioral Clustering / Behavioral Evolution.
  Prevents single-execution critique (trade_auditor scope) and
  cohort/corpus pattern inference (Phase 62 scope).
version: "1.0.0"
tags: [critique, mentor, behavioral, phase-60]
applies_to_profiles:
  - behavioral_mentor_agent
  - behavioral_mentor_agent._analyzer
---

# Critique Discipline (Mentor Variant)

## Scope

This skill governs behavioral_mentor_agent critique output. Every critique MUST:
- Scope to ONE account across MULTIPLE executions
- Structure output around: **Pattern Frequency** / **Behavioral Clustering** / **Behavioral Evolution**
- Cite every assertion via `[ref:<registry_id>:<field>]` grammar (see citation-discipline)

## Invariants

1. **Cross-trade scope**: At least 2+ executions must support any pattern claim.
2. **No single-execution critique**: Per-trade analysis is trade_auditor_agent scope.
3. **No corpus-level population patterns**: Phase 62 scope only.
4. **No causality claims**: "Behavior X increases AFTER event Y" requires Phase 62 causal substrate.

## Structure Template

```
**Pattern Frequency**
[ref:get_cross_trade_behavioral_patterns:patterns] shows [ref:behavioral_pattern:fomo_entry]
appearing in N/M executions (rate: [ref:get_cross_trade_behavioral_patterns:rate]) ...

**Behavioral Clustering**
[ref:get_behavioral_edges:*] — [behavioral cluster narrative] ...

**Behavioral Evolution**
[ref:get_behavioral_evolution_tool:*] — [trend direction] over [window] ...
```

## Anti-Patterns

- Do NOT name specific execution IDs when making pattern claims
- Do NOT invent pattern IDs not in registry/behavioral_pattern/
- Do NOT use phrases like "most traders" or "in general" (population-scope)

## Registry References

- `[ref:get_cross_trade_behavioral_patterns:*]` — cross-trade pattern frequencies
- `[ref:get_behavioral_edges:*]` — behavioral edge analysis
- `[ref:get_behavioral_evolution_tool:*]` — longitudinal behavioral trends
- `[ref:behavioral_pattern:<id>]` — pattern registry entries
