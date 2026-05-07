### get_news_context:

Returns news and event context (scheduled events, breaking headlines,
event proximity) relevant to the trade. **CURRENTLY STUBBED** — Phase
31 ships the real news pipeline. Calling this tool today returns a
rich `not_available` payload with `impact_on_decision: "HIGH"`.

Honour the gap: when this tool returns `status: "not_available"`,
acknowledge "News context unavailable — confidence reduced" in your
response and continue reasoning with the data you do have. Call this
tool ONLY when news context is load-bearing for the decision (e.g.
trade is within an hour of a scheduled high-impact event).

args:
- `trade_id`: trade identifier (required)

returns a JSON payload with `status` ("not_available"), `planned_phase`
("Phase 31"), `tool` ("get_news_context"), `would_provide`,
`impact_on_decision` ("HIGH"), and `unblocks_when`.

DO NOT:
- fabricate event names or headlines to fill the gap
- call this tool for every chat turn — only when event proximity matters

example:
~~~json
{
  "thoughts": ["The trader said NFP is later today — need to confirm event proximity."],
  "headline": "Checking news context (stubbed)",
  "tool_name": "get_news_context",
  "tool_args": {
    "trade_id": "abc-123"
  }
}
~~~
