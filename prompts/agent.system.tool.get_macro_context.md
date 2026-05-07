### get_macro_context:

Returns macro economic context (interest rate decisions, inflation data,
central bank bias) relevant to the trade. **CURRENTLY STUBBED** — Phase
33 ships the real macro ingestion pipeline. Calling this tool today
returns a rich `not_available` payload with `impact_on_decision: "HIGH"`.

Honour the gap: when this tool returns `status: "not_available"`,
acknowledge "Macro context unavailable — confidence reduced" in your
response and continue reasoning with the data you do have. Call this
tool ONLY when macro context is load-bearing for the decision (e.g.
trade is near a known FOMC date or a CPI release window).

args:
- `trade_id`: trade identifier (required)

returns a JSON payload with `status` ("not_available"), `planned_phase`
("Phase 33"), `tool` ("get_macro_context"), `would_provide`,
`impact_on_decision` ("HIGH"), and `unblocks_when`.

DO NOT:
- fabricate macro values to fill the gap — the system intentionally
  surfaces `not_available` so the Decision Framework can score it
- call this tool for every chat turn — only when macro is decisive

example:
~~~json
{
  "thoughts": ["Need to know if there's an FOMC decision window before this short fires."],
  "headline": "Checking macro context (stubbed)",
  "tool_name": "get_macro_context",
  "tool_args": {
    "trade_id": "abc-123"
  }
}
~~~
