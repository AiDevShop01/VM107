Your previous message was not a valid tool call. The orchestrator could not extract a JSON object containing `tool_name` and `tool_args` fields.

You MUST recover by emitting ONLY a single JSON object with this exact shape, with no prose before or after:

{
  "thoughts": ["brief reasoning about the next action"],
  "tool_name": "<exact tool name from your available tools list>",
  "tool_args": { "<arg_key>": "<arg_value>" }
}

**DO NOT:**
- Emit markdown reports, tables, or headings outside the JSON
- Wrap the JSON in code fences (```json is parsed as part of the text)
- Include narrative prose before the JSON
- Emit multiple JSON blocks — only one tool call per message
- Emit embedded JSON snippets (e.g. `{"score": null}`) inside prose; the orchestrator will mistakenly extract them

**DO:**
- Start your message with `{` and end with `}`
- Use the exact key names `tool_name` and `tool_args`
- If you have nothing more to report, call the `response` tool with `tool_args.text` containing your final output

Re-emit a single valid tool call now.
