"""VM107 FastMCP server (Phase 67 Plan 12).

Streamable-HTTP MCP server exposing two always-active CLOSE-state tools
to external MCP clients (Claude Desktop, Cursor):

    - mission.close.journal_prompts (REQ-67-4)
    - mission.close.surfaced_lesson (REQ-67-5)

Bearer auth via fastmcp.server.auth.providers.jwt.JWTVerifier
(env-driven JWKS_URI / ISSUER / AUDIENCE — no fallback defaults per
Phase 47.3 lock).

Per-session activation policy is DEFERRED to a follow-up phase
(load-bearing constraint #12 — Phase 67 v1 ships always-active 2 tools).

Pitfall 10 mitigation:
- FastMCP pinned to >=3.2,<4 (see VM107/requirements.txt).
- In FastMCP 3.x, BearerAuthProvider was renamed JWTVerifier; the auth
  kwargs (jwks_uri / issuer / audience / required_scopes) are identical.
- `stateless_http` is no longer a constructor arg in 3.x — pass it to
  `run()` instead (or set FASTMCP_STATELESS_HTTP env).
"""
from __future__ import annotations

import os

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier

# Env-driven config — fail-fast on missing (Phase 47.3 lock; CLAUDE.md
# "no `os.getenv("X", "default")` fallbacks"). The subscript form raises
# KeyError if the env var is absent.
JWKS_URI = os.environ["VM107_MCP_JWKS_URI"]
ISSUER = os.environ["VM107_MCP_ISSUER"]
AUDIENCE = os.environ["VM107_MCP_AUDIENCE"]
PORT = int(os.environ["VM107_MCP_PORT"])

# Required scope for any MCP client invocation. Tokens missing this scope
# get 403 from the auth provider's required_scopes check.
REQUIRED_SCOPES = ["mission_control:read"]

auth = JWTVerifier(
    jwks_uri=JWKS_URI,
    issuer=ISSUER,
    audience=AUDIENCE,
    required_scopes=REQUIRED_SCOPES,
)

mcp = FastMCP(
    "fingpt-vm107",
    auth=auth,
)

# Importing the tools package triggers @mcp.tool decorators that register
# tools onto the `mcp` instance above. Must be imported AFTER `mcp` is
# constructed so the decorators have something to bind to.
from . import tools  # noqa: E402, F401


if __name__ == "__main__":
    # streamable-http transport per OpenBB analysis recommendation.
    # stateless_http=True moved to run() in fastmcp 3.x (was constructor arg in 2.x).
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=PORT,
        path="/mcp",
        stateless_http=True,
    )
