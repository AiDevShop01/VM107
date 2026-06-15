"""Phase 85.1 agent invocation helper for the task dispatcher.

HTTP path to Agent Zero (NOT in-process). Plan 02's first design tried in-process
A0 invocation; deployment surfaced that the dispatcher process can't bootstrap A0
runtime (model proxy, capability registry, qdrant clients) without becoming a
parallel copy of vm107-agent-zero itself.

The HTTP path POSTs to /api/api_message on the existing vm107-agent-zero service.
A0 server already runs the full stack; the dispatcher just sends a message and
parses the response. agent_profile is delivered in the JSON body — A0 server
enforces routing internally (Pitfall 2 contract is now: agent_profile field MUST
be present in the request body, AND the message field).

Env vars (REQUIRED — fail-fast, no fallback defaults):
    VM107_AGENT_ZERO_URL    base URL of A0, e.g. http://vm107-agent-zero:80
    VM107_INTERNAL_TOKEN    X-API-KEY value (existing VM100<->VM107 service token)

Test-patchable surface:
    workers.agent_invocation._dispatch_agent_sync  — patch the whole function
        for tests that don't want HTTP at all (existing test pattern).
    workers.agent_invocation._post_message  — patch the HTTP transport only
        to assert request shape (Pitfall 2 ordering guard).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SEC = 300  # 5 min per task — long enough for slow LLMs


def _resolve_endpoint() -> tuple[str, str]:
    """Resolve A0 base URL + internal token. Fail-fast on missing config."""
    try:
        base = os.environ["VM107_AGENT_ZERO_URL"].rstrip("/")
    except KeyError as exc:
        raise RuntimeError(
            "VM107_AGENT_ZERO_URL env var REQUIRED (Phase 85.1 dispatcher HTTP path)."
        ) from exc
    try:
        token = os.environ["VM107_INTERNAL_TOKEN"]
    except KeyError as exc:
        raise RuntimeError(
            "VM107_INTERNAL_TOKEN env var REQUIRED (Phase 85.1 dispatcher HTTP path)."
        ) from exc
    return base, token


def _post_message(
    base_url: str,
    token: str,
    body: dict,
    timeout_sec: int = _DEFAULT_TIMEOUT_SEC,
) -> dict:
    """POST to /api/api_message. Separate function so tests can patch HTTP only."""
    resp = requests.post(
        f"{base_url}/api/api_message",
        headers={"Content-Type": "application/json", "X-API-KEY": token},
        data=json.dumps(body),
        timeout=timeout_sec,
    )
    resp.raise_for_status()
    return resp.json()


def _dispatch_agent_sync(
    profile_id: str,
    user_message: str,
) -> tuple[str, dict]:
    """Invoke an Agent Zero profile via HTTP and return (response_text, telemetry).

    Args:
        profile_id: Agent profile identifier (e.g. "vm107.macro_release_analyst").
        user_message: The prompt / instruction to deliver.

    Returns:
        (raw_output, telemetry) where:
          raw_output — A0's text response (usually JSON for analyst profiles).
          telemetry  — dict (HTTP path has no router internals; minimal shape
                       preserved for output_routing compatibility).

    Raises:
        RuntimeError: If A0 URL / token env vars are missing.
        requests.HTTPError: If A0 returns non-2xx.
        requests.Timeout: If A0 takes longer than _DEFAULT_TIMEOUT_SEC.

    Pitfall 2 contract (HTTP path): the request body MUST include both
        ``agent_profile`` AND ``message`` keys. A0 server's slot-30 router
        keys off the ``agent_profile`` value to route. Test guard:
        ``test_dispatch_agent_sync_sets_profile_id_before_monologue``.
    """
    base_url, token = _resolve_endpoint()

    body = {
        "agent_profile": profile_id,
        "message": user_message,
    }

    payload = _post_message(base_url, token, body)

    raw: str = payload.get("response", "")
    telemetry: dict[str, Any] = {
        "model_used": payload.get("model_used", "unknown"),
        "reason_chain": payload.get("reason_chain", []),
        "cost": payload.get("cost", {}),
        "fallback_used": payload.get("fallback_used", False),
        "b1_artifact_id": payload.get("b1_artifact_id"),
        "context_id": payload.get("context_id"),
    }

    return raw, telemetry
