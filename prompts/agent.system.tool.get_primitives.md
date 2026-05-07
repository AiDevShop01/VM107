### get_primitives:

Reads pre-computed market primitives from parquet for a trade.

V1 layer scope (LOCKED — anything else is rejected):
- L1: Volatility / Range — ATR, candle range, body ratio
- L2: Structure — swing highs/lows, BOS/CHoCH, failed structure
- L4: Compression — range contraction, volatility squeeze, inside bars
- L6: Liquidity — equal highs/lows, FVG, imbalance zones

Direct parquet read; idempotent; no recompute side-effects. NO support
for L3, L5, L7+. Asking for those raises a contract validation error.

args:
- `trade_id`: trade identifier (required)
- `timeframe`: one of M1, M5, M15, M30, H1, H4, D1 (required)
- `layers`: subset of `[1, 2, 4, 6]` (optional, default = all four)
- `lookback_bars`: integer 1..2000 (optional, default = 200)

returns a typed JSON payload with `trade_id`, `instrument`, `timeframe`,
and `layers` (one entry per requested layer with `count` and `bars`).

DO NOT:
- request layers outside `{1, 2, 4, 6}` — V1 will reject the call
- call this tool blindly — pull only the layers your reasoning actually
  needs (CONTEXT.md "Prefer minimal sufficient context")

example:
~~~json
{
  "thoughts": ["I need structure + compression context for this short setup."],
  "headline": "Reading L2 + L4 primitives",
  "tool_name": "get_primitives",
  "tool_args": {
    "trade_id": "abc-123",
    "timeframe": "M5",
    "layers": [2, 4]
  }
}
~~~
