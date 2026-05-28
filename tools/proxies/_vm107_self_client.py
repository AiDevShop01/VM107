"""Phase 70.5 Plan 07 — VM107 self-proxy client.

VM107 emitter endpoints are distinct from the VM107IdentityClient (identity
resolution). This lightweight client wraps VM107's own emitter API endpoints
that vm107.* proxy tools call self-referentially.

Reads VM107_API_URL from environment — no fallback defaults.
"""
from __future__ import annotations

import os

from fingpt_core.clients.base import BaseVMClient, RetryProfile


def _default_vm107_api_url() -> str:
    """Resolve VM107 self-proxy base URL.

    Reads `VM107_API_URL` env var. Raises RuntimeError if unset — no
    fallback defaults (memory rule: feedback_env_driven_no_fallbacks).
    """
    url = os.environ.get("VM107_API_URL")
    if not url:
        raise RuntimeError(
            "VM107_API_URL is required — set in docker-compose env_file or test fixture. "
            "No fallback defaults allowed (feedback_env_driven_no_fallbacks)."
        )
    return url


class Vm107SelfClient(BaseVMClient):
    """HTTP client for VM107's own emitter API endpoints.

    Used by vm107.* proxy tools that call VM107's REST emitter endpoints.
    Distinct from VM107IdentityClient (which is for identity resolution).

    Default base URL: read from `VM107_API_URL` env var (no fallback).
    """

    def __init__(
        self,
        base_url: str | None = None,
        profile: RetryProfile = RetryProfile.BALANCED,
        timeout: float = 30.0,
        connect_timeout: float = 5.0,
    ):
        """Initialize VM107 self-proxy client.

        Args:
            base_url: Base URL for VM107 service (default: $VM107_API_URL env var)
            profile: Retry profile configuration
            timeout: Total request timeout in seconds
            connect_timeout: Connection timeout in seconds
        """
        super().__init__(
            base_url=base_url or _default_vm107_api_url(),
            profile=profile,
            timeout=timeout,
            connect_timeout=connect_timeout,
        )
