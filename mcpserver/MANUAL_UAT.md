# VM107 FastMCP Server — Manual UAT

Phase 67 Plan 12 — manual verification scaffold for VALIDATION.md row 6.
Covers the two always-active CLOSE-state MCP tools shipped on the VM107
FastMCP server:

- `mission.close.journal_prompts` (REQ-67-4)
- `mission.close.surfaced_lesson` (REQ-67-5)

The server speaks streamable-HTTP MCP at `${VM107_HOST}:${VM107_MCP_PORT}/mcp`
and validates Bearer tokens via the JWKS configured at
`${VM107_MCP_JWKS_URI}` (issuer = `${VM107_MCP_ISSUER}`, audience =
`${VM107_MCP_AUDIENCE}`, required scope = `mission_control:read`).

---

## Prerequisites

1. VM107 container is up with all 6 required env vars set (fail-fast — if
   any is missing, the container will not start):
   - `VM107_MCP_JWKS_URI`
   - `VM107_MCP_ISSUER`
   - `VM107_MCP_AUDIENCE`
   - `VM107_MCP_PORT`
   - `VM100_BASE_URL`
   - `VM100_INTERNAL_TOKEN`
2. VM100 backend is reachable from VM107 at `${VM100_BASE_URL}`.
3. Plan 13 has shipped `/api/mission-control/close/reflection-prompts`
   on VM100 (the `mission.close.journal_prompts` MCP tool returns 502 / 5xx
   until that endpoint is wired). Plan 08's `/api/mission-control/surfaced-lesson`
   is already live, so `mission.close.surfaced_lesson` can be exercised
   immediately.
4. You have a JWT signed by the configured issuer with:
   - `aud = ${VM107_MCP_AUDIENCE}`
   - `iss = ${VM107_MCP_ISSUER}`
   - `scope` claim containing `mission_control:read`
   - `exp` in the future

A quick smoke-test JWT can be issued by the VM100 auth service (see
`VM100/backend/auth/` for the relevant minting endpoint).

---

## Test 1: Claude Desktop Handshake

**Goal:** Confirm Claude Desktop can list + invoke both MCP tools.

**Steps:**

1. Edit Claude Desktop config at
   `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
   and append `fingpt-vm107` under `mcpServers`:

   ```json
   {
     "mcpServers": {
       "fingpt-vm107": {
         "command": "curl",
         "args": [
           "-N",
           "-H", "Authorization: Bearer <YOUR_JWT_HERE>",
           "http://${VM107_HOST}:${VM107_MCP_PORT}/mcp"
         ]
       }
     }
   }
   ```

   Replace `${VM107_HOST}`, `${VM107_MCP_PORT}`, and `<YOUR_JWT_HERE>`
   with concrete values.

2. Quit + restart Claude Desktop.

3. Open the Settings → Developer → MCP Servers panel. Verify
   `fingpt-vm107` appears with status connected.

4. In a Claude conversation, type:

   > Use mission.close.surfaced_lesson for account_id=42 date=2026-05-25

5. **Expected:** Claude announces it is calling the tool, the FastMCP
   server returns the `SurfacedLessonContract` JSON, Claude summarises
   the lesson. If `_demo=true` is present, Claude should mention the
   degraded state + banner.

6. Repeat with:

   > Use mission.close.journal_prompts for account_id=42 date=2026-05-25

7. **Expected:** Claude calls the tool, receives the
   `ReflectionPromptSetContract` JSON (4 selected prompts + rejected
   candidates + coherence_score), Claude renders the prompts as
   conversational reflection questions.

8. Document the outcome (success / failure) and attach a screenshot of
   the Claude conversation alongside the response payload.

---

## Test 2: Cursor IDE Integration

**Goal:** Confirm Cursor can discover the tools via MCP and invoke them
inline from the AI side-panel.

**Steps:**

1. In Cursor, open `Settings → Features → MCP Servers` and add a new
   server entry mirroring Test 1 (same URL + Authorization header).

2. Reload the Cursor window. Open the AI side-panel and verify the
   `mission.close.surfaced_lesson` + `mission.close.journal_prompts`
   tools appear in the tool list.

3. From the AI chat, mention the tool with `@`:

   > @mission.close.journal_prompts account_id=42 date=2026-05-25

4. **Expected:** Cursor invokes the tool over MCP, displays the returned
   JSON inline + offers to summarize. If the underlying VM100 endpoint
   isn't shipped yet (Plan 13 dependency), the tool will surface an HTTP
   5xx — document that gracefully.

5. Document the outcome (success / failure) + screenshot.

---

## Test 3: Bearer Auth Negative Tests

**Goal:** Confirm the server rejects unauthenticated / under-scoped
clients per the JWTVerifier configuration.

All three sub-tests can be exercised with `curl` against the
`/mcp` endpoint. The MCP handshake's `initialize` JSON-RPC call is the
simplest probe; any 4xx response before the protocol completes is the
expected behaviour.

### 3a. Invalid bearer token

```bash
curl -i \
  -H "Authorization: Bearer not-a-real-token" \
  -H "Content-Type: application/json" \
  -X POST \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  "http://${VM107_HOST}:${VM107_MCP_PORT}/mcp"
```

**Expected:** HTTP 401 with `WWW-Authenticate: Bearer ...` header.

### 3b. Valid token, missing required scope

Mint a JWT with `aud = ${VM107_MCP_AUDIENCE}` and `iss = ${VM107_MCP_ISSUER}`
but WITHOUT `mission_control:read` in the `scope` claim. Issue the same
`initialize` call.

**Expected:** HTTP 403 — token is authentic but lacks the required scope.
The server SHOULD include a `WWW-Authenticate` challenge naming the
missing scope (`mission_control:read`).

### 3c. Valid token with `mission_control:read` scope

Issue the request again with a fully-formed token (correct `aud`, `iss`,
`scope`, non-expired `exp`).

**Expected:** HTTP 200 + valid JSON-RPC `initialize` response. A
follow-up `tools/list` call returns both
`mission.close.journal_prompts` and `mission.close.surfaced_lesson`.

### 3d. (Optional) Missing Authorization header entirely

```bash
curl -i \
  -H "Content-Type: application/json" \
  -X POST \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  "http://${VM107_HOST}:${VM107_MCP_PORT}/mcp"
```

**Expected:** HTTP 401.

Document the response code + body for each sub-test.

---

## Sign-off

| Test                          | Outcome | Notes |
| ----------------------------- | ------- | ----- |
| 1. Claude Desktop handshake   |         |       |
| 2. Cursor IDE integration     |         |       |
| 3a. Invalid bearer token      |         |       |
| 3b. Missing required scope    |         |       |
| 3c. Valid token + scope       |         |       |
| 3d. Missing Authorization     |         |       |

**Notes / deferred items:**

- Plan 13 wires the VM100 `/api/mission-control/close/reflection-prompts`
  proxy endpoint. Until that lands, `mission.close.journal_prompts`
  returns 5xx — this is expected and validates the chokepoint pattern.
- Per-session activation policy (per load-bearing constraint #12) is
  deferred to a follow-up phase. v1 ships always-active 2 tools.
