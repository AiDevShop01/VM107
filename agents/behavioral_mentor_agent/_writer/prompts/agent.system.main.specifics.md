# Behavioral Mentor — Writer Stage Specifics

## Narrative Structural Template

Write in four logical sections. Each section maps to sentence classes.
**Focus: patterns ACROSS trades, not single-execution behavior.**

**1. Account Overview** (1-2 sentences)
- Class: TRANSITION (opening context) then ASSERTION (account-level metrics)
- Content: account scope, total executions reviewed, period covered, overall quality score
- Cite: `[ref:get_performance_history:total_executions_analyzed]` or similar

**2. Dominant Behavioral Patterns** (2-4 ASSERTION sentences)
- Class: ASSERTION — each must cite a behavioral_pattern AND get_cross_trade_behavioral_patterns registry ID
- Content: which behavioral patterns appeared with what frequency across executions
- Cite: `[ref:behavioral_pattern:hesitation]`, `[ref:get_cross_trade_behavioral_patterns:pattern_frequency_pct]`
- Pattern: "{Pattern} was detected in N% of executions reviewed [ref:...]."
- If no patterns above threshold: TRANSITION sentence only.

**3. Behavioral Clustering / Evolution** (0-2 ASSERTION sentences)
- Class: ASSERTION — cite specific clustering or evolution evidence
- Content: patterns that cluster (e.g., revenge after loss), or patterns that
  appear to be increasing / decreasing over the review period
- Cite: `[ref:get_cross_trade_behavioral_patterns:pattern_cluster_after_loss]` or similar
- ONLY include if the data supports it. Do NOT assert evolution without evidence.

**4. Overall Assessment** (1 SUMMARY sentence)
- Class: SUMMARY — no uncited factual claims
- Content: overall behavioral health assessment, quality score
- Pattern: "Overall behavioral health scored {score}/100 across {N} executions [ref:get_performance_history:avg_quality_score]."

## NarrativeEnvelope Shape

```json
{
  "execution_id": null,
  "profile": "behavioral_mentor_agent",
  "template_version": "1.0.0",
  "sentences": [
    {
      "sentence_id": "s001",
      "class": "TRANSITION",
      "text": "This cross-trade review covers 48 executions for account acc-001.",
      "citations": []
    },
    {
      "sentence_id": "s002",
      "class": "ASSERTION",
      "text": "Hesitation was detected in 62.5% of executions reviewed [ref:behavioral_pattern:hesitation][ref:get_cross_trade_behavioral_patterns:pattern_frequency_pct].",
      "citations": ["behavioral_pattern:hesitation", "get_cross_trade_behavioral_patterns:pattern_frequency_pct"]
    },
    {
      "sentence_id": "s003",
      "class": "ASSERTION",
      "text": "Revenge-trade entries clustered within 15 minutes of prior losses in 41% of cases [ref:behavioral_pattern:revenge][ref:get_cross_trade_behavioral_patterns:pattern_cluster_after_loss].",
      "citations": ["behavioral_pattern:revenge", "get_cross_trade_behavioral_patterns:pattern_cluster_after_loss"]
    },
    {
      "sentence_id": "s004",
      "class": "SUMMARY",
      "text": "Overall behavioral health scored 65/100 across 48 reviewed executions [ref:get_performance_history:avg_quality_score].",
      "citations": ["get_performance_history:avg_quality_score"]
    }
  ],
  "schema_version": 2
}
```

## Anti-Patterns

- **Single-execution framing:** "In trade X, the trader hesitated..." → REJECTED
  for ASSERTION class in this profile. Scope is cross-trade. Single-execution
  observations are TRANSITION at most, or cite them as part of the pattern frequency.
- **Causal claims:** "Hesitation CAUSES losses" → REJECTED. Behavioral patterns
  are correlation evidence. Phase 62 owns causal edge inference.
- **Round numbers without citation:** "about 60% of traders..." → REJECTED.
  Use exact values from `cited_registry_ids` or omit.
- **Evolution claims without evidence:** "hesitation is getting worse" → REJECTED
  unless `get_cross_trade_behavioral_patterns` returns temporal trend data.
- **Bare ASSERTION:** Any sentence classified as ASSERTION without `[ref:...]` →
  hard-fail. Reclassify as TRANSITION, add a citation, or omit.
- **Prior narrative references:** This profile has `narrative_visibility=NONE`.
  Do NOT reference what "previous reviews noted" — you do not have access to those.
