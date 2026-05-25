"""VM107 FastMCP server package.

Phase 67 Plan 12 — FastMCP streamable-http server exposing two always-active
CLOSE-state MCP tools to external clients (Claude Desktop, Cursor):

  - mission.close.journal_prompts  (REQ-67-4 wrap of vm107.reflection_prompt)
  - mission.close.surfaced_lesson  (REQ-67-5 wrap of vm100 surfaced_lesson endpoint)

Both tools route through the VM100 chokepoint (see CONTEXT.md §3) — MCP
does NOT bypass the privacy / auth machinery. Env-driven config; fail-fast
on missing env vars (Phase 47.3 lock).

NOTE: directory name is `mcpserver/` (not `mcp/`) to avoid shadowing the
PyPI `mcp` SDK that fastmcp depends on. Pitfall: a local `mcp/__init__.py`
under VM107 (which is at the front of sys.path via root conftest) would
shadow `import mcp.types` inside fastmcp and break the entire MCP stack.
"""
