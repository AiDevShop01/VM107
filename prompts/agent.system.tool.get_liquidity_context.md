### get_liquidity_context:

Read ACTIVE liquidity zones (FVG, equal highs/lows, imbalance) for an instrument and timeframe. "Active" means not yet swept/filled/invalidated/expired per Phase 28 event engine. Embedded status:

- `status: "ok"` + populated zone arrays → here is what's currently in play (empty arrays = looked, no active zones)
- `status: "not_available"` → liquidity zones layer or Phase 28 lifecycle data is unbuilt for this instrument×timeframe

Use this when the trader's question references liquidity zones, FVGs, equal highs/lows, supply/demand near entry.

  "tool_name": "get_liquidity_context",
  "tool_args": {
    "instrument": "EURUSD",
    "timeframe": "M5",
    "lookback_bars": 100
  }

Args:
- `instrument` (required): symbol from Tier-1 context
- `timeframe` (required): one of M1, M5, M15, M30, H1, H4, D1
- `lookback_bars` (optional): 1..500, default 100

Notes:
- Active-only — historical/swept zones are intentionally excluded (V1 scope).
- Pure data tool — no side effects, idempotent.
- Lookback values above 500 are silently clamped to 500.
