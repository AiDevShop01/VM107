# Trade Auditor Agent — Specifics

## Pipeline Overview

`trade_auditor_agent` is the Phase 60 single-execution critique profile.

**Scope:** One trade execution at a time. No cross-trade analysis (that is
`behavioral_mentor_agent`). No week-rollup (that is `weekly_review_agent`).

## Sub-Profile Map

| Sub-profile | Dotted Agent ID | Stage Role |
|-------------|-----------------|------------|
| `_reader/` | `trade_auditor_agent._reader` | Retrieves evidence from VM100 / replay artifacts / Phase 57 analytics |
| `_analyzer/` | `trade_auditor_agent._analyzer` | Calls typed VM107 tools to score and pattern-match |
| `_writer/` | `trade_auditor_agent._writer` | Composes NarrativeEnvelope with cited sentence array |

Sub-profile prompts live at the respective `prompts/agent.system.main.role.md` paths.
Skill rules (critique-discipline, pattern-recognition) live at
`agents/trade_auditor_agent/skills/`.

## Shadow-Mode Rollout

In Phase 60, `trade_auditor_agent` persists narratives to the `review_narrative`
table (Postgres, append-only WORM) but the UI does NOT display them.
Narratives are available via internal read-back endpoints for validation only.
