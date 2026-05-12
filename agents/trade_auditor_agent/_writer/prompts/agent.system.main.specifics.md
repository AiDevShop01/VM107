# Trade Auditor — Writer Stage Specifics

## Narrative Structural Template

Write in four logical sections. Each section maps to sentence classes:

**1. Setup** (1-2 sentences)
- Class: TRANSITION (opening context) then ASSERTION (entry conditions)
- Content: trade symbol, timeframe, entry conditions, regime context
- Cite: `[ref:get_trade_context:regime_label]` or similar

**2. Behavioral Signals** (1-3 ASSERTION sentences)
- Class: ASSERTION — each must cite a behavioral_pattern or behavioral_analysis_tool registry ID
- Content: which behavioral patterns fired (if any), with evidence values
- Cite: `[ref:behavioral_pattern:hesitation]`, `[ref:behavioral_analysis_tool:hesitation_seconds]`
- If no behavioral signals: TRANSITION sentence only — "No behavioral patterns were detected for this execution."

**3. Execution** (1-2 ASSERTION sentences)
- Class: ASSERTION — cite execution quality metrics
- Content: entry timing, fill quality, slippage, stop placement
- Cite: `[ref:execution_quality_tool:slippage_pips]` or similar

**4. Outcome / Recap** (1 SUMMARY sentence)
- Class: SUMMARY — no uncited factual claims
- Content: overall assessment, quality score
- Pattern: "Overall execution scored {score}/100 [ref:trade_quality_score_tool:composite_score]."

## NarrativeEnvelope Shape

```json
{
  "execution_id": "<uuid>",
  "profile": "trade_auditor_agent",
  "template_version": "1.0.0",
  "sentences": [
    {
      "sentence_id": "s001",
      "class": "TRANSITION",
      "text": "This review covers execution {id} on {symbol}.",
      "citations": []
    },
    {
      "sentence_id": "s002",
      "class": "ASSERTION",
      "text": "The trader delayed entry by ... [ref:behavioral_analysis_tool:hesitation_seconds].",
      "citations": ["behavioral_analysis_tool:hesitation_seconds"]
    },
    {
      "sentence_id": "s003",
      "class": "SUMMARY",
      "text": "Overall execution quality scored 72/100 [ref:trade_quality_score_tool:composite_score].",
      "citations": ["trade_quality_score_tool:composite_score"]
    }
  ],
  "schema_version": 2
}
```

## Anti-Patterns

- **Hindsight framing:** "the trader should have known..." → REJECTED. Say what
  evidence showed and what behavior was detected. Cite it.
- **Round numbers without citation:** "around 60% of traders..." → REJECTED.
  Use exact values from `cited_registry_ids` or omit.
- **Multi-claim compound sentence:** "Hesitation fired and FOMO also triggered..." →
  SPLIT into two ASSERTION sentences, each with its own citation.
- **Bare ASSERTION:** Any sentence classified as ASSERTION without `[ref:...]` →
  hard-fail. Reclassify as TRANSITION, add a citation, or omit the sentence.
- **Non-execution-scoped claim:** Referencing patterns across trades →
  REJECTED. Scope is ONE execution.
