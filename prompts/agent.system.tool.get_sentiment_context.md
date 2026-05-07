### get_sentiment_context:

Returns sentiment context (retail positioning, options skew, social
sentiment). **CURRENTLY STUBBED** — Wave 8 ships the real sentiment
service. Calling this tool today returns a rich `not_available`
payload with `impact_on_decision: "LOW"`.

Honour the gap: when this tool returns `status: "not_available"`,
note the gap briefly but do NOT materially reduce confidence — the
locked impact is LOW, meaning sentiment is a tiebreaker, not a
decision driver. Call this tool ONLY when retail positioning or skew
would tip a borderline read.

args:
- `trade_id`: trade identifier (required)

returns a JSON payload with `status` ("not_available"), `planned_phase`
("Wave 8"), `tool` ("get_sentiment_context"), `would_provide`,
`impact_on_decision` ("LOW"), and `unblocks_when`.

DO NOT:
- fabricate retail positioning or social sentiment values
- treat sentiment as decisive — it's a tiebreaker

example:
~~~json
{
  "thoughts": ["Setup is borderline — checking if extreme retail long positioning supports the contrarian short."],
  "headline": "Checking sentiment context (stubbed)",
  "tool_name": "get_sentiment_context",
  "tool_args": {
    "trade_id": "abc-123"
  }
}
~~~
