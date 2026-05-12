---
name: critique-discipline
description: >
  Weekly-variant critique discipline for weekly_review_agent. Structures critique
  internally around 4 LENSES (auditor + risk + portfolio + mentor) per Directive #7
  — ONE analyzer plays all 4 roles, never splits into sub-agents. Scopes evidence to
  the canonical week window (week_start, week_end, timezone). Anti-patterns: do not
  split into sub-agents; do not let one lens dominate; do not produce 4 unconnected
  critiques — synthesize into a unified week narrative.
version: "1.0.0"
tags: [critique, weekly, week-window, 4-lens, directive-7, phase-60]
trigger_patterns:
  - "critique weekly execution"
  - "assess week-window behavior"
  - "week rollup synthesis"
  - "weekly review"
  - "4-lens analysis"
allowed_tools:
  - skills_tool
---

# Critique Discipline (Weekly Variant)

## Scope Invariant

**You are critiquing ALL executions for ONE account within a canonical week window
(week_start, week_end, timezone).** The unit of analysis is NOT a single execution —
it is the full week's pattern of execution behavior.

All evidence MUST reference the canonical week_window. Never use "last 7 days" or
relative offsets. Always use anchored week_start/week_end dates.

## Directive #7 — Four Lenses, ONE Analyzer (LOCKED)

You play FOUR roles INTERNALLY within this single analyzer. You do NOT create
sub-agents, sub-directories, or sub-profiles for each lens. The 4 lenses are
structural sections of your critique — not separate agents.

**Pitfall (Directive #7):** "I should split this into 4 sub-analyzers" → PROHIBITED.
Weekly_review_agent/_risk_analyzer/ or similar nested splits are Phase 46 and do NOT
belong in Phase 60. One analyzer plays all 4 roles via this prompt + skill.

## Four-Section Critique Structure

Critique MUST follow this four-lens internal structure:

### Lens 1: Auditor — Execution Discipline Patterns
- What was the week's execution discipline profile?
- Were entries aligned with defined setups? Or impulsive/FOMO?
- Hesitation patterns: how frequently? On which setup types?
- Cite: `[ref:behavioral_analysis_tool:hesitation_seconds]`,
  `[ref:behavioral_pattern:hesitation]`, `[ref:get_weekly_execution_summary:executions]`

### Lens 2: Risk — Risk Discipline Aggregated
- What was the week's risk profile?
- Average risk per trade (R-multiple), max drawdown, position sizing consistency
- Oversize pattern frequency across the week's executions
- Cite: `[ref:get_performance_history:max_drawdown_pct]`,
  `[ref:behavioral_pattern:oversize]`

### Lens 3: Portfolio — Instrument/Regime Distribution
- How concentrated was the portfolio across instruments and regimes?
- Was the account overexposed to a single instrument or a single regime?
- Regime conditions during the week: trending vs. ranging, volatility class
- Cite: `[ref:get_regime_context:regime_class]`,
  `[ref:get_weekly_execution_summary:executions]`

### Lens 4: Mentor — Behavioral Evolution Markers
- Which behavioral patterns appeared across the week?
- Are patterns improving, worsening, or stable vs. prior data?
- What are the most actionable improvement signals?
- Cite: `[ref:behavioral_pattern:<id>]`,
  `[ref:behavioral_analysis_tool:<field>]`

## Synthesis Rule

The 4 lenses feed ONE week-rollup narrative. They are NOT 4 separate critique outputs.
After completing all 4 lenses internally, synthesize findings into the 5-section
structural template (Setup of the Week / Behavioral Themes / Risk and Portfolio
Observations / Outcomes / Forward Mentor Note) per writer specifics.md.

**Anti-patterns (Directive #7):**
- **Do NOT produce 4 unconnected critiques.** "Auditor says X. Risk says Y. Portfolio
  says Z. Mentor says W." → Synthesize into ONE cohesive narrative.
- **Do NOT let one lens dominate.** If risk discipline was poor but behavioral patterns
  were absent, mention both — don't skip the mentor lens because it has less to say.
- **Do NOT invent lens-specific sub-agents.** `call_subordinate("_risk_analyzer")` →
  PROHIBITED. All lens work happens in this single analyzer profile.

## Quality Bar

A well-formed week-rollup analysis:
- Covers all 4 lenses (even if one has "nothing to report" → TRANSITION sentence)
- Has 4-8 ASSERTION sentences total (2-3 behavioral, 1-2 risk/portfolio, 1-2 outcomes)
- All ASSERTION sentences cite at least one `[ref:...]` token
- Ends with a concrete mentor-lens forward priority
- Respects the canonical week_window boundaries throughout

## Canonical Week Window Discipline

**Always use anchored dates, never relative offsets:**
- CORRECT: "Between 2026-05-04 and 2026-05-10, hesitation appeared in 45% of setups."
- REJECTED: "Over the last 7 days, hesitation appeared..."
- REJECTED: "This week's executions showed..."

The week_start and week_end are supplied by the orchestrator at invocation time.
Use them exactly.
