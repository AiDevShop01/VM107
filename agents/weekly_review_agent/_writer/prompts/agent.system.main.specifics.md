# Weekly Review Agent — Writer Stage Specifics

## Narrative Structural Template

Write in five logical sections for a week-rollup synthesis. Each section maps to
sentence classes. Draw from all 4 analyzer lenses.

**1. Setup of the Week** (1-2 sentences)
- Class: TRANSITION (opening context) then ASSERTION (week-level metrics)
- Content: canonical week window, total executions reviewed, overall quality score
- Cite: `[ref:get_weekly_execution_summary:executions]` or
  `[ref:get_performance_history:total_executions_analyzed]`
- Pattern: "This review covers {N} executions closed between {week_start} and {week_end}
  for account {account_id} [ref:get_weekly_execution_summary:executions]."

**2. Behavioral Themes** (2-3 ASSERTION sentences)
- Class: ASSERTION — each must cite a behavioral_pattern AND behavioral_analysis tool
- Content: which behavioral patterns appeared this week with what frequency
- Draw from: AnalyzerOutput.findings.auditor + findings.mentor
- Cite: `[ref:behavioral_pattern:hesitation]`, `[ref:behavioral_analysis_tool:hesitation_seconds]`
- Pattern: "Hesitation was the dominant execution pattern, observed in {N}% of setups
  reviewed [ref:behavioral_pattern:hesitation][ref:behavioral_analysis_tool:hesitation_seconds]."

**3. Risk and Portfolio Observations** (1-2 ASSERTION sentences)
- Class: ASSERTION — cite risk or portfolio evidence
- Content: key risk metric for the week + portfolio concentration or regime exposure
- Draw from: AnalyzerOutput.findings.risk + findings.portfolio
- Cite: `[ref:get_performance_history:max_drawdown_pct]`, `[ref:get_regime_context:regime_class]`
- Pattern: "Maximum drawdown for the week was {N}%, with exposure concentrated in
  {regime_class} conditions [ref:get_performance_history:max_drawdown_pct][ref:get_regime_context:regime_class]."

**4. Outcomes** (1 ASSERTION sentence)
- Class: ASSERTION — overall week performance
- Content: win rate, quality score summary
- Cite: `[ref:get_performance_history:win_rate_pct]` and/or
  `[ref:get_performance_history:avg_quality_score]`
- Pattern: "The week closed with a {win_rate}% win rate and an average quality score
  of {score}/100 across {N} executions [ref:get_performance_history:win_rate_pct][ref:get_performance_history:avg_quality_score]."

**5. Forward Mentor Note** (1 SUMMARY sentence)
- Class: SUMMARY — no uncited factual claims
- Content: one forward-looking behavioral priority from the mentor lens
- Draw from: AnalyzerOutput.findings.mentor.improvement_signals
- Pattern: "Priority for the coming week: [behavioral focus]."

## NarrativeEnvelope Shape

```json
{
  "execution_id": null,
  "profile": "weekly_review_agent",
  "template_version": "1.0.0",
  "sentences": [
    {
      "sentence_id": "s001",
      "class": "TRANSITION",
      "text": "This review covers 12 executions closed between 2026-05-04 and 2026-05-10.",
      "citations": []
    },
    {
      "sentence_id": "s002",
      "class": "ASSERTION",
      "text": "Hesitation was the dominant execution pattern, observed in 45% of setups reviewed [ref:behavioral_pattern:hesitation][ref:behavioral_analysis_tool:hesitation_seconds].",
      "citations": ["behavioral_pattern:hesitation", "behavioral_analysis_tool:hesitation_seconds"]
    },
    {
      "sentence_id": "s003",
      "class": "ASSERTION",
      "text": "Maximum drawdown for the week was 4.2%, with exposure concentrated in trending conditions [ref:get_performance_history:max_drawdown_pct][ref:get_regime_context:regime_class].",
      "citations": ["get_performance_history:max_drawdown_pct", "get_regime_context:regime_class"]
    },
    {
      "sentence_id": "s004",
      "class": "ASSERTION",
      "text": "The week closed with a 52% win rate and an average quality score of 68/100 across 12 executions [ref:get_performance_history:win_rate_pct][ref:get_performance_history:avg_quality_score].",
      "citations": ["get_performance_history:win_rate_pct", "get_performance_history:avg_quality_score"]
    },
    {
      "sentence_id": "s005",
      "class": "SUMMARY",
      "text": "Priority for the coming week: maintain entry discipline on A+ setups where hesitation cost was highest.",
      "citations": []
    }
  ],
  "schema_version": 2
}
```

## Anti-Patterns

- **Single-execution dominance:** "Trade ABC on Wednesday showed..." → This is NOT a
  single-execution critique. Single executions may appear as illustrative examples in
  TRANSITION sentences but cannot anchor ASSERTION sentences.
- **Causal claims:** "Hesitation CAUSED the losses" → REJECTED. Phase 60 identifies
  patterns; Phase 62 owns causal inference.
- **Relative week framing:** "last 7 days" → REJECTED. Use canonical week_start/week_end.
- **Prior narrative references:** "As last week's review noted..." → REJECTED.
  `narrative_visibility=NONE` means you do NOT have access to prior narratives.
- **Bare ASSERTION:** Any sentence classified ASSERTION without `[ref:...]` →
  hard-fail. Reclassify as TRANSITION, add a citation, or omit.
- **ConfidenceVector in output:** Do NOT include a `confidence_vector` field —
  the orchestrator computes it deterministically after validation.
