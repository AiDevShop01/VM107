"""VM107 FastMCP tool registrations (Phase 67 Plan 12).

Importing this package triggers the @mcp.tool decorators on each tool
module, which register the tool on the FastMCP server instance defined
in mcpserver.server. The standard FastMCP registration pattern.
"""
from . import close_journal_prompts  # noqa: F401,E402
from . import close_surfaced_lesson  # noqa: F401,E402

__all__ = ["close_journal_prompts", "close_surfaced_lesson"]
