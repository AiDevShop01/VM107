### get_strategy_definition:

Loads the YAML strategy framework (criteria, hard_rejects, scoring) for a
given `strategy_id`. The first shipped strategy is `model_2_option_1_short`.
Use this tool when you need to apply strategy-specific evaluation rules,
check hard rejects, or quote criteria back to the trader.

args:
- `strategy_id`: strategy identifier (required) — must match a YAML file
  under `agents/agent0/strategies/<id>.yaml`

returns a typed JSON payload with `id`, `version`, `description`,
`criteria` (list of `{name, required}` where `required` is `true` |
`false` | `"preferred"`), `hard_rejects`, and optional `scoring`.

DO NOT:
- assume strategies exist — call this tool first and respect the
  `not found` / `malformed` error message if the file is missing or invalid
- treat `required: "preferred"` as a hard rule — it's a bonus weight,
  Phase 47.3 will assign the exact weight

example:
~~~json
{
  "thoughts": ["The trader is using model_2_option_1_short — load its hard_rejects so I can check the breakout-into-HVN rule."],
  "headline": "Loading strategy YAML",
  "tool_name": "get_strategy_definition",
  "tool_args": {
    "strategy_id": "model_2_option_1_short"
  }
}
~~~
