### get_trade_context:

Returns curated journal data for a trade: instrument, direction, strategy_id,
entry/SL/TP prices, notes, timeframe, checklist snapshot, and (when
available) a summary of the last formal evaluation. Use this when you need
entry/exit details that the lightweight Tier-1 context doesn't include.

args:
- `trade_id`: trade identifier (required)

returns a typed JSON payload with `trade_id`, `instrument`, `direction`,
`strategy_id`, `entry_price`, `stop_loss_price`, `take_profit_price`,
`notes`, `timeframe`, `checklist_snapshot_text`, `last_evaluation`.

DO NOT:
- call this tool when the lightweight context already answers the question
- call this tool repeatedly within a single turn — one fetch per trade

example:
~~~json
{
  "thoughts": ["I need the entry, stop, and take-profit for this trade before I can comment on R:R."],
  "headline": "Fetching curated journal data",
  "tool_name": "get_trade_context",
  "tool_args": {
    "trade_id": "abc-123"
  }
}
~~~
