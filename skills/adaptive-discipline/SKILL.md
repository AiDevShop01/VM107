---
name: adaptive-discipline
description: >
  Constitutional skill enforcing epistemic discipline when referencing or interpreting
  adaptive intelligence outputs. Prevents agents from treating adaptive hypothesis
  signals as canonical trading truth, from implying recommendations are actionable
  without human authorization, or from phrasing drift observations as certainty claims.
  Phase 62's primary guard against adaptive contamination in mentor prose.
version: "1.0.0"
phase: 62
scope: constitutional
trigger_patterns:
  - "drift"
  - "adaptive"
  - "behavioral pattern suggests"
  - "the evidence suggests"
  - "strategy appears to be"
  - "[ref:drift_report"
  - "[ref:counterfactual_aggregate"
  - "[ref:behavioral_evolution"
  - "[ref:pattern_cluster"
  - "[ref:adaptive_recommendation"
  - "SHADOW_ONLY"
  - "BOOTSTRAP OBSERVATION"
  - "LIVE SHADOW-MODE"
allowed_tools:
  - get_drift_report
  - get_counterfactual_scenario_stats
  - get_behavioral_drift_summary
tags: [phase-62, constitutional, adaptive, drift, epistemic-discipline, shadow-only, ctx-dec-1, ctx-dec-14, ctx-dec-15]
---

# Adaptive Discipline

## Why This Skill Exists

Phase 62 introduces adaptive intelligence signals — weekly drift observations,
counterfactual aggregates, and behavioral evolution series. These are HYPOTHESIS
PROPOSALS, not trading instructions. The most dangerous failure mode is treating
a drift observation as a confirmed diagnosis or treating an adaptive recommendation
as a mandate.

**The adaptive intelligence layer does NOT optimize. It proposes hypotheses.**
**Humans authorize epistemic change.**

## Core Tone Constraint

When citing adaptive signals, use the phrase:

> "the evidence suggests possible drift"

NEVER use:

> "the strategy is now fixed"
> "drift has been corrected"
> "the system now uses the improved parameter"
> "you should now trade differently based on this"

The difference is ontological, not stylistic. Adaptive signals are advisory
cognition artifacts. They propose epistemic updates for human review. They do
NOT instruct.

## Citation Grammar

All adaptive artifact references MUST use the approved citation grammar:

```
[ref:drift_report:<cohort_snapshot_id>:<field>]
[ref:counterfactual_aggregate:<cohort_snapshot_id>:<field>]
[ref:behavioral_evolution:<series_id>:<field>]
[ref:pattern_cluster:<cluster_id>:<field>]
[ref:adaptive_recommendation:<recommendation_id>:<field>]
```

NEVER cite:
- Bare numeric values without a citation anchor
- Another mentor's narrative or inference chain
- A prior conversation output as an adaptive source

## SHADOW_ONLY Framing

When citing an adaptive recommendation or drift observation, always surface the
SHADOW_ONLY framing explicitly:

> "This is a SHADOW_ONLY adaptive observation — it has not been reviewed or
> authorized for application to live trading parameters."

NEVER imply the adaptive recommendation is production truth. NEVER frame the
output as "the system now believes" or "current configuration shows."

## BOOTSTRAP vs. LIVE Framing

Origin mode must be surfaced accurately:

- `HISTORICAL_BOOTSTRAP`: prefix the observation with "BOOTSTRAP OBSERVATION: "
- `LIVE_FORWARD_ACCUMULATION`: prefix with "LIVE SHADOW-MODE ADAPTIVE SIGNAL: "

Both are SHADOW_ONLY. The distinction is whether the data came from the initial
historical backfill or from the ongoing forward accumulation.

## Forbidden Patterns

These patterns represent CTX-DEC-1/14/15 violations:

| Forbidden | Reason |
|-----------|--------|
| "the strategy is now fixed" | Implies human authorization already happened |
| "drift has been corrected" | Implies an apply action was taken |
| "your winrate improved after the recommendation" | Implies causation from an advisory signal |
| "I recommend changing X to Y" | Adaptive tools propose, humans authorize |
| "based on the adaptive system's decision" | No "decision" — only hypotheses |

## Constitutional Application

This skill activates whenever an agent references adaptive citations in prose.
Cite the adaptive artifact, frame it as an observation, and ALWAYS label it
SHADOW_ONLY unless the human has explicitly authorized the epistemic change.
