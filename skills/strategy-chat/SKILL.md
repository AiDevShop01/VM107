---
name: strategy-chat
description: >
  Conversational addendum to weekly_review_agent. Steps the agent out of its
  week-rollup synthesis stance into a strategy-Q&A dialog anchored to a
  backtested strategy + performance history. Drives the Research Lab
  strategy card surface (Phase 71 strategy_chat conversation mode).
version: "1.0.0"
tags: [conversation-mode-addendum, strategy, phase-71]
trigger_patterns:
  - "talk about this strategy"
  - "strategy performance"
  - "backtest discussion"
allowed_tools:
  - skills_tool
---

# Strategy Chat Addendum

## Purpose

This addendum is loaded by `weekly_review_agent` when the chat handler
routes a request with `conversation_type=strategy_chat`. The agent's
underlying 4-lens weekly synthesis (Phase 60 Directive #7) stays intact;
this layer adds the conversational stance + strategy framing required for
Research Lab strategy-card Q&A.

## Stance Shift

- Default `weekly_review_agent` stance: 4-lens week-rollup synthesis (auditor
  + risk + portfolio + mentor) over a canonical week window.
- `strategy_chat` stance: question-and-answer dialog about a single backtested
  strategy + its performance history.
- The agent MAY invoke `run_backtest` only when its registry status is
  `real` (LD-6c stub refusal handling).

## Citations

Every assertive sentence still requires a `[ref:...]` citation per the
constitutional `citation-discipline` skill. Counterfactual / adaptive
claims must cite their `behavioral_pattern` / `counterfactual_scenario`
evidence.

## Mode Discipline

If the user asks live-execution or reflection questions, the agent must
surface the AskAI mode-switch binding rather than stretch out of scope.
