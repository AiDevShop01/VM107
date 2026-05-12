# Behavioral Mentor Agent — Specifics

## Pipeline Overview

`behavioral_mentor_agent` is the Phase 60 cross-trade behavioral pattern critique
profile.

**Scope:** Multiple trade executions for ONE account. Cross-trade behavioral
analysis — frequency of patterns, repeated failure modes, behavioral evolution.
No single-execution focus (that is `trade_auditor_agent`). No week-rollup synthesis
(that is `weekly_review_agent`). No prior narrative reads — `narrative_visibility=NONE`.

## Sub-Profile Map

| Sub-profile | Dotted Agent ID | Stage Role |
|-------------|-----------------|------------|
| `_reader/` | `behavioral_mentor_agent._reader` | Retrieves cross-trade evidence from Phase 57 analytics, Phase 58 derived intelligence, Phase 56 event store |
| `_analyzer/` | `behavioral_mentor_agent._analyzer` | Calls behavioral_analysis + get_performance_history + get_cross_trade_behavioral_patterns |
| `_writer/` | `behavioral_mentor_agent._writer` | Composes NarrativeEnvelope with cited sentence array emphasizing cross-trade patterns |

Sub-profile prompts live at the respective `prompts/agent.system.main.role.md` paths.
Skill rules (critique-discipline, pattern-recognition) live at
`agents/behavioral_mentor_agent/skills/`.

## Scope Invariants

- **Account scope required.** All evidence is scoped to one account's execution history.
- **No execution_scope.** Evidence spans ALL executions for the account, not one.
- **No narrative reads.** Prior auditor or mentor narratives are NOT in scope —
  `narrative_visibility=NONE` is enforced at the dispatcher and VM100 endpoint levels.
  This is intentional: behavioral patterns must be inferred from deterministic
  evidence (events, snapshots, behavioral edges), NOT from prior interpretive narratives.

## Shadow-Mode Rollout

In Phase 60, `behavioral_mentor_agent` persists narratives to the `review_narrative`
table (Postgres, append-only WORM) but the UI does NOT display them.
Narratives are available via internal read-back endpoints for validation only.
