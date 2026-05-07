### get_liquidity_context:

Reads Phase 27 layer-6 liquidity primitives — FVG zones, equal highs/lows,
imbalance zones — for a trade. Direct parquet read; idempotent; no
recompute side-effects.

args:
- `trade_id`: trade identifier (required)
- `timeframe`: one of M1, M5, M15, M30, H1, H4, D1 (required)
- `lookback_bars`: integer (optional, default = 200)

returns a typed JSON payload with `trade_id`, `instrument`, `timeframe`,
and four bucketed lists:
- `fvg_zones`: `{timestamp, upper, lower, direction, filled}`
- `equal_highs`: `{timestamp, price, swept}`
- `equal_lows`: `{timestamp, price, swept}`
- `imbalance_zones`: `{timestamp, upper, lower, label}`

DO NOT:
- call this when you only need basic structure — `get_primitives`
  with `layers=[2]` is cheaper if you don't need FVG / equal highs/lows
- assume liquidity is always populated — empty lists are valid
  (e.g., new instruments without enough history)

example:
~~~json
{
  "thoughts": ["Check liquidity above the swing high before this short — is there a clean target?"],
  "headline": "Reading liquidity context",
  "tool_name": "get_liquidity_context",
  "tool_args": {
    "trade_id": "abc-123",
    "timeframe": "M5"
  }
}
~~~
