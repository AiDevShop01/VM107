### get_performance_history:

Returns historical performance for the trader's strategy (strategy win
rate, recent drawdown, similar setup outcomes). **CURRENTLY STUBBED** —
Phase 47.4 ships the real Postgres trade-evaluation history. Calling
this tool today returns a rich `not_available` payload with
`impact_on_decision: "MEDIUM"`.

Honour the gap: when this tool returns `status: "not_available"`,
acknowledge "Performance history unavailable — cannot weight by past
outcomes" and reason from the strategy definition + present setup
quality. Call this tool ONLY when prior-trade outcomes would change
the weight you put on this setup.

args:
- `trade_id`: trade identifier (required)

returns a JSON payload with `status` ("not_available"), `planned_phase`
("Phase 47.4"), `tool` ("get_performance_history"), `would_provide`,
`impact_on_decision` ("MEDIUM"), and `unblocks_when`.

DO NOT:
- fabricate win rates or drawdown figures
- call this tool when the trader is asking about the present setup
  rather than recent strategy performance

example:
~~~json
{
  "thoughts": ["Want to know if this strategy has been in a recent drawdown before sizing."],
  "headline": "Checking performance history (stubbed)",
  "tool_name": "get_performance_history",
  "tool_args": {
    "trade_id": "abc-123"
  }
}
~~~
