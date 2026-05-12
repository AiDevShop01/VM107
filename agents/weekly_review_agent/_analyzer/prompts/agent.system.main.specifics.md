# Weekly Review Agent — Analyzer Stage Specifics

## Analyzer Tool Map (RESEARCH.md lines 856-864)

Call tools in this recommended order:

| Step | Tool | Purpose | Feeds Lens |
|------|------|---------|------------|
| 1 | `get_weekly_execution_summary(account_id, week_start, week_end, timezone)` | Batch read of all execution_ids + snapshots closed in week window | All lenses (primary batch source) |
| 2 | `get_performance_history(account_id)` | Account-level aggregates (win rate, drawdown, avg quality, position sizing) | Auditor + Risk + Portfolio lenses |
| 3 | `get_regime_context(week_start, week_end)` | Regime conditions during the week (trending/ranging, volatility class) | Portfolio lens + ConfidenceVector `regime_data_freshness_hours` |
| 4 | `behavioral_analysis(execution_id)` | Per-execution behavioral signals | Mentor lens + Auditor lens (call for 3-5 representative executions) |

## Four-Lens Protocol

After calling the tools above, structure your analysis through 4 lenses INTERNALLY:

### Lens 1: Auditor — Execution Discipline
Aggregate across all executions in the week:
- Setup adherence rate (entries that matched a defined setup vs. impulsive entries)
- Entry timing discipline (hesitation patterns across the week's executions)
- Exit discipline (early exits, target hits vs. manual overrides)
- Cite: `[ref:behavioral_analysis_tool:hesitation_seconds]`, `[ref:get_weekly_execution_summary:executions]`

### Lens 2: Risk — Risk Discipline
Aggregate risk metrics across the week:
- Average risk per trade as R-multiple
- Max drawdown within the week window
- Position sizing consistency (oversize pattern frequency)
- Cite: `[ref:get_performance_history:max_drawdown_pct]`, `[ref:behavioral_pattern:oversize]`

### Lens 3: Portfolio — Instrument/Regime Distribution
Analyze portfolio composition across the week:
- Instrument concentration (% of executions on most-traded symbol)
- Regime exposure (were trades concentrated in trending vs. ranging conditions?)
- Correlated exposure (multiple positions in same regime/instrument class simultaneously)
- Cite: `[ref:get_regime_context:regime_class]`, `[ref:get_weekly_execution_summary:executions]`

### Lens 4: Mentor — Behavioral Evolution
Assess behavioral trajectory:
- Which behavioral patterns appeared this week? At what frequency?
- Improving vs. worsening relative to prior data available (not prior narratives)
- Recurring failure modes that appear consistently across the week
- Cite: `[ref:behavioral_pattern:<id>]`, `[ref:behavioral_analysis_tool:<field>]`

## AnalyzerOutput Required Shape

```json
{
  "execution_id": null,
  "quality_score": 68,
  "behavioral_signals": [
    {
      "pattern_id": "hesitation",
      "registry_id": "behavioral_pattern:hesitation",
      "confidence": 0.88,
      "evidence_field": "hesitation_seconds",
      "frequency_pct": 45.0,
      "cited_source": "behavioral_analysis_tool"
    }
  ],
  "execution_metrics": {
    "win_rate_pct": 52.0,
    "avg_quality_score": 68,
    "max_drawdown_pct": 4.2,
    "total_executions_analyzed": 12,
    "week_start": "2026-05-04",
    "week_end": "2026-05-10"
  },
  "findings": {
    "auditor": {
      "setup_adherence_rate": 0.83,
      "hesitation_frequency_pct": 45.0,
      "exit_discipline_rate": 0.75,
      "summary_note": "Mostly disciplined week; 2 impulsive entries on Wednesday."
    },
    "risk": {
      "avg_risk_per_trade_r": 0.85,
      "max_drawdown_pct": 4.2,
      "oversize_frequency_pct": 8.3,
      "summary_note": "Risk discipline strong; single oversize entry on GBPUSD."
    },
    "portfolio": {
      "dominant_instrument": "EURUSD",
      "instrument_concentration_pct": 58.3,
      "regime_distribution": {"trending": 0.67, "ranging": 0.33},
      "summary_note": "Concentrated in EURUSD; most trades in trending regime."
    },
    "mentor": {
      "dominant_behavioral_patterns": ["hesitation"],
      "pattern_trend": "stable",
      "recurring_failure_modes": ["hesitation on A+ setups"],
      "improvement_signals": ["no revenge trades this week"],
      "summary_note": "Hesitation persists on high-quality setups; revenge pattern absent."
    }
  },
  "cited_registry_ids": [
    "behavioral_pattern:hesitation",
    "behavioral_analysis_tool:hesitation_seconds",
    "get_performance_history:max_drawdown_pct",
    "get_regime_context:regime_class",
    "get_weekly_execution_summary:executions"
  ],
  "schema_version": 2
}
```

## Behavioral Pattern Registry IDs (Phase 58 V1)

Cite via `[ref:behavioral_pattern:<id>]`:

| Pattern ID | Trigger Condition |
|------------|-------------------|
| `hesitation` | Entry delay > 3 seconds after signal |
| `fomo` | Entry after price moved > 0.3% past signal zone |
| `late_entry` | Entry > 5 bars after ideal entry bar |
| `revenge` | Entry within 15 minutes of prior losing trade, same symbol |
| `oversize` | Position size > 2x account-risk-adjusted standard |

## Anti-Patterns

- Do NOT create sub-agent calls (Directive #7): _risk_analyzer, _portfolio_analyzer,
  _mentor_analyzer are Phase 46. Play all 4 lenses internally.
- Do NOT use relative week offsets like "last 7 days" — use exact week_start/week_end
  from the AnalyzerInput.
- Do NOT read prior narratives — `narrative_visibility=NONE` blocks those endpoints.
- Do NOT call `lookup_replay_artifact`, `fetch_replay_frame` — reader-tier tools denied here.
- Do NOT call `persist_narrative` — writer-tier, denied here.
- Do NOT leave `cited_registry_ids` empty if you detected behavioral signals.
- Do NOT assert causal edges like `Behavior-INCREASES_AFTER-Outcome` (Phase 62).
