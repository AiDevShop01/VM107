# Weekly Review Agent — Specifics

## Pipeline Overview

`weekly_review_agent` is the Phase 60 week-rollup synthesis profile.

**Scope:** All trade executions closed within a canonical week window
(week_start, week_end, timezone) for ONE account. Week-level synthesis —
multi-lens analysis (auditor + risk + portfolio + mentor) played INTERNALLY
by a single analyzer. No 4-specialist split (Directive #7 — that is Phase 46).
No prior narrative reads — `narrative_visibility=NONE`.

## Sub-Profile Map

| Sub-profile | Dotted Agent ID | Stage Role |
|-------------|-----------------|------------|
| `_reader/` | `weekly_review_agent._reader` | Retrieves week-window evidence via get_weekly_execution_summary + per-execution analytics + replay artifacts |
| `_analyzer/` | `weekly_review_agent._analyzer` | Plays 4 lenses INTERNALLY (auditor + risk + portfolio + mentor) using behavioral_analysis, get_performance_history, get_regime_context, get_weekly_execution_summary |
| `_writer/` | `weekly_review_agent._writer` | Composes NarrativeEnvelope with cited week-rollup narrative following 5-section structural template |

Sub-profile prompts live at the respective `prompts/agent.system.main.role.md` paths.
Skill rules (critique-discipline-weekly, pattern-recognition-weekly) live at
`agents/weekly_review_agent/skills/`.

## Canonical Week Window

The week window is supplied as (week_start: ISO date, week_end: ISO date, timezone: str).
This anchored representation — NOT a "last N days" relative offset — is what allows
replay reproducibility. Every evidence call uses these exact boundaries.

Example: `week_start=2026-05-04, week_end=2026-05-10, timezone=America/New_York`

## Scope Invariants

- **Account scope required.** All evidence is scoped to one account_id.
- **No execution_scope.** Evidence spans all executions closed within the week window.
- **No narrative reads.** Prior auditor or mentor narratives are NOT in scope —
  `narrative_visibility=NONE` is enforced at the dispatcher and VM100 endpoint levels.
  Week-level synthesis must be grounded in deterministic evidence only.

## Shadow-Mode Rollout

In Phase 60, `weekly_review_agent` persists narratives to the `review_narrative`
table (Postgres, append-only WORM) but the UI does NOT display them.
Narratives are available via internal read-back endpoints for validation only.
The Sunday 23:59 UTC cron schedule fires `weekly_review_pipeline_job` over
canonical time windows.
