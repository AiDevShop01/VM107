---
name: critique-discipline
description: >
  Mentor-variant critique discipline for behavioral_mentor_agent. Scopes critique to
  CROSS-TRADE behavioral patterns for ONE account. Structures output around Pattern
  Frequency / Behavioral Clustering / Behavioral Evolution markers. Anti-patterns:
  do not critique a single trade (trade_auditor's job); do not infer cohort/corpus
  patterns comparing across accounts (Phase 62's job).
version: "1.0.0"
tags: [critique, mentor, cross-trade, account-scoped, phase-60]
trigger_patterns:
  - "critique behavioral patterns"
  - "assess cross-trade behavior"
  - "mentor review"
  - "account behavioral analysis"
allowed_tools:
  - skills_tool
---

# Critique Discipline (Mentor Variant)

## Scope Invariant

**You are critiquing cross-trade behavioral patterns for ONE account.** The unit of
analysis is NOT a single execution — it is a pattern appearing across multiple
executions within the account scope.

All behavioral frequency claims MUST be attributable to the account's execution
history as retrieved by `get_cross_trade_behavioral_patterns`. No cross-account
comparisons. No population statistics without an account-scoped source.

## Structural Template

Critique MUST follow this three-section structure:

### 1. Pattern Frequency
- What behavioral patterns appeared in this account's execution history?
- At what frequency? (Cite: `[ref:get_cross_trade_behavioral_patterns:pattern_frequency_pct]`)
- Only assert patterns that appeared above threshold (>10% of executions). Do NOT
  mention patterns that did not detectably fire.

### 2. Behavioral Clustering
- Do patterns cluster around specific conditions? (e.g., revenge_trade after losses)
  Cite: `[ref:get_cross_trade_behavioral_patterns:pattern_cluster_after_loss]`
- Do patterns co-occur? (e.g., fomo + late_entry appearing together)
  Cite: `[ref:get_cross_trade_behavioral_patterns:pattern_cooccurrence]`
- ONLY include if data supports clustering. Do NOT invent clustering without evidence.

### 3. Behavioral Evolution
- Has pattern frequency changed over time? Improving or worsening?
  Cite: `[ref:get_cross_trade_behavioral_patterns:pattern_trend]`
- ONLY assert evolution if the data explicitly supports it. Absence of trend data
  means no evolution claim can be made.

## Anti-Patterns (Mentor-Specific)

- **Do NOT critique a single execution** — "In trade X, the trader hesitated" →
  That is `trade_auditor_agent`'s scope. Behavioral mentor critiques patterns,
  not individual trades.
- **Do NOT compare this account to other accounts** — "This trader hesitates more
  than 80% of traders..." → That is Phase 62's scope (corpus analysis). Phase 60
  is strictly within-account.
- **Do NOT assert `Behavior-INCREASES_AFTER-Outcome` causal edges** — Phase 62
  owns causal inference. Phase 60 identifies patterns and clustering.
- **Do NOT use vague frequency language** — "often hesitates" → Cite the actual
  frequency: `[ref:get_cross_trade_behavioral_patterns:pattern_frequency_pct]`
- **Do NOT reference prior narratives** — `narrative_visibility=NONE` means prior
  auditor or mentor narratives are NOT in scope. Do not say "as previous reviews noted."

## Quality Bar

A well-formed cross-trade critique has 3-6 ASSERTION sentences, each with at least
one `[ref:...]`. Frequency, clustering, and evolution claims must all cite the
`get_cross_trade_behavioral_patterns` tool. If you cannot cite a claim, reclassify
as TRANSITION or omit entirely.
