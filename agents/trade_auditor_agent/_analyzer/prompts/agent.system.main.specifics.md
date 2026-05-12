# Trade Auditor — Analyzer Stage Specifics

## Analyzer Tool Map

Call tools in this recommended order:

| Step | Tool | Purpose | Output Field |
|------|------|---------|--------------|
| 1 | `get_trade_quality_score(execution_id)` | Composite quality score 0-100 | `quality_score` |
| 2 | `behavioral_analysis(execution_id)` | Behavioral pattern detection (hesitation, FOMO, etc.) | `behavioral_signals` |
| 3 | `execution_quality(execution_id)` | Slippage, fill quality, entry/exit timing | `execution_metrics` |
| 4 | `get_behavioral_edges(execution_id)` | Neo4j behavioral edges active at this execution | Merge into `behavioral_signals` |

## Behavioral Pattern Registry IDs (Phase 58 V1)

These are the V1 behavioral patterns from Phase 58. Cite them as `[ref:behavioral_pattern:<id>]`:

- `hesitation` — delayed entry > 3 seconds after signal
- `fomo` — entered after price moved > 0.3% past signal zone
- `late_entry` — entry > 5 bars after ideal entry bar
- `revenge` — entered within 15 minutes of a prior losing trade on same symbol
- `oversize` — position size > 2x the account-risk-adjusted standard

## AnalyzerOutput Required Shape

```json
{
  "execution_id": "<uuid>",
  "quality_score": 72,
  "behavioral_signals": [
    {
      "pattern_id": "hesitation",
      "registry_id": "behavioral_pattern:hesitation",
      "confidence": 0.87,
      "evidence_field": "hesitation_seconds"
    }
  ],
  "execution_metrics": {
    "slippage_pips": 1.2,
    "fill_quality": "good",
    "entry_timing_score": 65
  },
  "cited_registry_ids": [
    "behavioral_analysis_tool:hesitation_seconds",
    "behavioral_pattern:hesitation"
  ],
  "schema_version": 2
}
```

## Anti-Patterns

- Do NOT reference other trades in your output. Scope is ONE execution.
- Do NOT infer cross-trade behavioral patterns (that is behavioral_mentor_agent).
- Do NOT call `lookup_replay_artifact`, `fetch_replay_frame`, or `get_trade_context`
  (those are reader-tier tools — denied in your agent.yaml).
- Do NOT call `persist_narrative` (that is writer-tier — denied in your agent.yaml).
- Do NOT leave `cited_registry_ids` empty if you found behavioral signals.
  An empty list signals to the writer that no behavioral evidence was retrieved.

## Scope Enforcement

All tool calls carry signed `X-Agent-Scope` claims injected by the orchestrator.
You NEVER supply scope. The orchestrator ensures `execution_scope` is set.
