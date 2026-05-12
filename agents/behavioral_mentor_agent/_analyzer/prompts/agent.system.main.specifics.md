# Behavioral Mentor — Analyzer Stage Specifics

## Analyzer Tool Map

Call tools in this recommended order:

| Step | Tool | Purpose | Output Field |
|------|------|---------|--------------|
| 1 | `get_performance_history(account_id)` | Account-level aggregates (win rate, drawdown, avg quality) | `execution_metrics` + `quality_score` |
| 2 | `get_cross_trade_behavioral_patterns(account_id)` | Cross-trade pattern frequency + clustering | `behavioral_signals` (primary) |
| 3 | `behavioral_analysis(execution_id)` | Per-execution behavioral signals for representative trades | Merge into `behavioral_signals` for frequency evidence |

## Behavioral Pattern Registry IDs (Phase 58 V1)

These are the V1 behavioral patterns from Phase 58. Cite them as `[ref:behavioral_pattern:<id>]`.
Pattern frequency is expressed as a percentage of executions in the account scope
where the pattern was detected:

- `hesitation` — delayed entry > 3 seconds after signal
- `fomo` — entered after price moved > 0.3% past signal zone
- `late_entry` — entry > 5 bars after ideal entry bar
- `revenge` — entered within 15 minutes of a prior losing trade on same symbol
- `oversize` — position size > 2x the account-risk-adjusted standard

## AnalyzerOutput Required Shape

```json
{
  "execution_id": null,
  "quality_score": 65,
  "behavioral_signals": [
    {
      "pattern_id": "hesitation",
      "registry_id": "behavioral_pattern:hesitation",
      "confidence": 0.92,
      "evidence_field": "pattern_frequency_pct",
      "frequency_pct": 62.5,
      "cited_source": "get_cross_trade_behavioral_patterns"
    },
    {
      "pattern_id": "revenge",
      "registry_id": "behavioral_pattern:revenge",
      "confidence": 0.78,
      "evidence_field": "pattern_cluster_after_loss",
      "frequency_pct": 41.0,
      "cited_source": "get_cross_trade_behavioral_patterns"
    }
  ],
  "execution_metrics": {
    "win_rate_pct": 44.2,
    "avg_quality_score": 65,
    "max_drawdown_pct": 8.3,
    "total_executions_analyzed": 48
  },
  "cited_registry_ids": [
    "behavioral_pattern:hesitation",
    "get_cross_trade_behavioral_patterns:pattern_frequency_pct",
    "behavioral_pattern:revenge",
    "get_cross_trade_behavioral_patterns:pattern_cluster_after_loss"
  ],
  "schema_version": 2
}
```

## Anti-Patterns

- Do NOT critique a single execution. Scope is ACCOUNT_SCOPED — multiple executions.
- Do NOT infer `Behavior-INCREASES_AFTER-Outcome` causal edges (Phase 62, not Phase 60).
- Do NOT compare this account to other accounts or population norms (Phase 62).
- Do NOT read prior narratives — `narrative_visibility=NONE` blocks those endpoints.
- Do NOT call `lookup_replay_artifact`, `fetch_replay_frame`, or `get_trade_context`
  (those are reader-tier tools — denied in your agent.yaml).
- Do NOT call `persist_narrative` (that is writer-tier — denied in your agent.yaml).
- Do NOT call `execution_quality` — that is single-execution scope, denied here.
- Do NOT leave `cited_registry_ids` empty if you found behavioral signals.

## Scope Enforcement

All tool calls carry signed `X-Agent-Scope` claims injected by the orchestrator.
You NEVER supply scope. The orchestrator ensures `cross_trade_visibility=ACCOUNT_SCOPED`.
