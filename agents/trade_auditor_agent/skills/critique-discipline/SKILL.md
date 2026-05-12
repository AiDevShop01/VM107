---
name: critique-discipline
description: >
  Auditor-variant critique discipline for trade_auditor_agent. Scopes critique to a
  single execution_id. Structures output around Entry Assessment / Behavioral Signals /
  Execution Quality. Prevents cross-trade references and multi-execution inferences.
version: "1.0.0"
tags: [critique, auditor, single-execution, phase-60]
trigger_patterns:
  - "critique execution"
  - "audit trade"
  - "assess entry"
  - "evaluate execution quality"
allowed_tools:
  - skills_tool
---

# Critique Discipline (Auditor Variant)

## Scope Invariant

**You are critiquing ONE execution.** `execution_id` is the anchor for every claim.
All behavioral signals, all quality scores, all evidence MUST be attributable to
this single execution. No cross-trade references. No population statistics.

## Structural Template

Critique MUST follow this three-section structure:

### 1. Entry Assessment
- Was the entry signal aligned with the regime? (Cite: `[ref:get_trade_context:regime_label]`)
- Was entry timing within the acceptable window? (Cite: `[ref:execution_quality_tool:entry_timing_score]`)
- Was position sizing appropriate? (Cite: `[ref:get_trade_context:account_risk_pct]`)

### 2. Behavioral Signals
- List any behavioral patterns detected (from `behavioral_analysis` output)
- Cite each pattern: `[ref:behavioral_pattern:<id>]`
- If no behavioral patterns detected: state "No behavioral patterns detected for this execution."
  Do NOT invent behavioral signals.

### 3. Execution Quality
- Slippage and fill quality (Cite: `[ref:execution_quality_tool:slippage_pips]`)
- Stop placement relative to structure
- Exit discipline

## Anti-Patterns (Auditor-Specific)

- **Do NOT reference other trades** — even to say "this trader tends to..." →
  That is `behavioral_mentor_agent`'s scope.
- **Do NOT infer behavioral patterns from a single execution alone** —
  `behavioral_analysis_tool` detects patterns within this execution; you cannot
  extrapolate to a cross-trade trend from one data point.
- **Do NOT use vague magnitude language** — "relatively large drawdown" →
  Cite the actual MAE value: `[ref:trade_analytics:max_adverse_excursion_pips]`
- **Do NOT assess "should have" framing** — cite what the evidence showed;
  avoid counterfactual hindsight statements.

## Quality Bar

A well-formed critique has 3-6 ASSERTION sentences, each with at least one `[ref:...]`.
If you cannot cite a claim, reclassify as TRANSITION or omit entirely.
Brevity with citation integrity beats length with bare assertions.
