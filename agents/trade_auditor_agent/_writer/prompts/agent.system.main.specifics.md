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

**ALWAYS respond with a single raw JSON object matching this schema. No markdown
fences in the response body, no wrappers, no explanatory prose before or after
the JSON.** The orchestrator calls `NarrativeEnvelope.model_validate()` and
rejects any deviation. `confidence_vector` MUST be `null` — the orchestrator
fills it after the envelope is sealed (CTX-§9 LOCKED).

```json
{
  "schema_version": "1.0",
  "profile": "trade_auditor_agent",
  "execution_id": "<uuid>",
  "sentences": [
    {
      "schema_version": "1.0",
      "sentence_index": 0,
      "sentence_class": "TRANSITION",
      "text": "This review covers execution {id} on {symbol}.",
      "citations": [],
      "unsourced": false
    },
    {
      "schema_version": "1.0",
      "sentence_index": 1,
      "sentence_class": "ASSERTION",
      "text": "The trader delayed entry by 4.2 seconds [ref:behavioral_analysis_tool:hesitation_seconds].",
      "citations": [
        {
          "schema_version": "1.0",
          "registry_id": "behavioral_analysis_tool",
          "field": "hesitation_seconds",
          "frame_anchor": null,
          "resolved_at": null
        }
      ],
      "unsourced": false
    },
    {
      "schema_version": "1.0",
      "sentence_index": 2,
      "sentence_class": "SUMMARY",
      "text": "Overall execution quality scored 72/100 [ref:trade_quality_score_tool:composite_score].",
      "citations": [
        {
          "schema_version": "1.0",
          "registry_id": "trade_quality_score_tool",
          "field": "composite_score",
          "frame_anchor": null,
          "resolved_at": null
        }
      ],
      "unsourced": false
    }
  ],
  "loaded_skills": [],
  "confidence_vector": null
}
```

**Field-name reminders:**
- Use `sentence_class` (not `class`), `sentence_index` (not `sentence_id`), `unsourced` (not `is_unsourced`)
- Each citation is an **object** with `registry_id` + `field`, NOT a string
- `loaded_skills` is `[]` unless skills were loaded
- `confidence_vector: null` — orchestrator owns this

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
