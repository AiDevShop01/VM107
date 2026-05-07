### get_regime_context:

Returns market regime classification (trend regime, volatility regime,
correlation regime) for the instrument. **CURRENTLY STUBBED** — Phase
34 ships the real regime classifier. Calling this tool today returns a
rich `not_available` payload with `impact_on_decision: "MEDIUM"`.

Honour the gap: when this tool returns `status: "not_available"`,
acknowledge "Regime context unavailable — confidence moderately
reduced" in your response and lean on the structure / compression
primitives that are available. Call this tool ONLY when regime context
would change your read of the setup (e.g. compression breakout in a
ranging vs trending regime behaves differently).

args:
- `trade_id`: trade identifier (required)

returns a JSON payload with `status` ("not_available"), `planned_phase`
("Phase 34"), `tool` ("get_regime_context"), `would_provide`,
`impact_on_decision` ("MEDIUM"), and `unblocks_when`.

DO NOT:
- fabricate regime labels — say "regime unknown" instead
- call this tool when L2 structure already answers the question

example:
~~~json
{
  "thoughts": ["Compression looks valid but I want to know if we're in a ranging regime where breakouts fail."],
  "headline": "Checking regime context (stubbed)",
  "tool_name": "get_regime_context",
  "tool_args": {
    "trade_id": "abc-123"
  }
}
~~~
