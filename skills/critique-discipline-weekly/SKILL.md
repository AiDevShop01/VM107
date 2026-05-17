---
name: critique-discipline-weekly
description: >
  Weekly-variant critique discipline for weekly_review_agent.
  Structures critique internally around 4 LENSES (auditor + risk + portfolio + mentor)
  per Directive #7 — ONE analyzer plays all 4 roles internally.
  Scopes evidence to canonical week window (week_start, week_end, timezone).
  Prevents lens-splitting into sub-agents and enforces synthesis into ONE cohesive week narrative.
version: "1.0.0"
tags: [critique, weekly, review, phase-60]
applies_to_profiles:
  - weekly_review_agent
  - weekly_review_agent._analyzer
---

# Critique Discipline (Weekly Review Variant)

## Scope

This skill governs weekly_review_agent critique output. Every critique MUST:
- Scope to a canonical week window (week_start, week_end, timezone)
- Apply all 4 lenses INTERNALLY (auditor / risk / portfolio / mentor)
- Emit ONE cohesive week narrative (no separate sections per lens in output)
- Cite every assertion via `[ref:<registry_id>:<field>]` grammar (see citation-discipline)

## The 4 Internal Lenses

Apply these lenses in your reasoning before synthesizing the week narrative:

1. **Auditor Lens**: Entry/exit quality across the week's executions
2. **Risk Lens**: Position sizing discipline, max drawdown, stop adherence
3. **Portfolio Lens**: Instrument concentration, session distribution, regime alignment
4. **Mentor Lens**: Cross-execution behavioral patterns within the week

## Invariants

1. **One narrative output**: Synthesize the 4 lenses into ONE cohesive output.
2. **Temporal scope**: Only reference executions within the canonical week window.
3. **No sub-agent delegation**: Do NOT suggest spawning separate agents per lens.
4. **Evidence-bound**: Every statement must be supported by a registered tool result.

## Structure Template

```
**Week of [week_start] — [N] executions**

[Synthesized opening: key regime + behavioral context]

**Trade Quality**
[ref:get_weekly_execution_summary:avg_overall_score] across [N] executions.
[ref:regime_analysis_tool:regime_distribution] for the week ...

**Behavioral Patterns**
[ref:get_cross_trade_behavioral_patterns:patterns] observed:
- [ref:behavioral_pattern:fomo_entry]: N occurrences ...

**Adaptation Signal**
[ref:get_adaptive_recommendations_tool:*] — [recommendation narrative] ...
```

## Anti-Patterns

- Do NOT produce separate "Auditor Section" / "Risk Section" / etc. in output
- Do NOT reference executions outside the week window
- Do NOT invent behavioral pattern IDs

## Registry References

- `[ref:get_weekly_execution_summary:*]` — week-scope execution summaries
- `[ref:get_cross_trade_behavioral_patterns:*]` — cross-trade patterns within week
- `[ref:get_adaptive_recommendations_tool:*]` — week-level recommendations
- `[ref:behavioral_pattern:<id>]` — pattern registry entries
