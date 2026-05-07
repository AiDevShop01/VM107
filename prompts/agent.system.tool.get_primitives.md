### get_primitives:

Read computed structural primitives (BOS/CHoCH/displacement/compression/exhaustion patterns) for an instrument and timeframe. Returns the most recent N bars per requested layer with embedded status:

- `status: "ok"` + populated layers → here is what we found (zero rows is valid — empty is not the same as missing)
- `status: "not_available"` → the primitives partition for this instrument×timeframe is unbuilt or VM102 is unreachable

Use this when the trader's question references structure (BOS, CHoCH, displacement candles), pattern context, or recent swing points.

  "tool_name": "get_primitives",
  "tool_args": {
    "instrument": "EURUSD",
    "timeframe": "M5",
    "layers": [1, 2, 4, 6],
    "lookback_bars": 100
  }

Args:
- `instrument` (required): symbol from Tier-1 context (e.g., "EURUSD", "BTCUSDT")
- `timeframe` (required): one of M1, M5, M15, M30, H1, H4, D1
- `layers` (optional): subset of [1, 2, 4, 6]. Default = all four.
- `lookback_bars` (optional): how many bars back to read, 1..500, default 100.

Notes:
- Pure data tool — no side effects, idempotent.
- Lookback values above 500 are silently clamped to 500.
- On transport failure, returns `status: "not_available"` with `meta.planned_phase` describing what would unblock.
