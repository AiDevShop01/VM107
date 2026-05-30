"""Phase 73 Plan 08 — VM107-side per-strategy weights loader.

Sibling to TierThresholdLoader (single-responsibility, not extension —
planner picked sibling over extend per Plan 73-08 RESEARCH alternatives).

Cross-VM contract (Phase 39 lock + memory directive): reads weights via
the VM100 typed API at::

    GET ${VM100_STRATEGY_WEIGHTS_URL}?strategy_id=<id>
    → {"strategy_id": ..., "weights_version": int,
       "weights": {category: int 0..100, ...}}

NEVER reads VM100's Postgres directly. The VM100 endpoint is the one and
only source of truth; we are a thin HTTP client.

Project lock — env-driven config, no fallback defaults:
- URL comes from ``VM100_STRATEGY_WEIGHTS_URL`` env var; KeyError fail-fast.
- Missing strategy → ``StrategyWeightsNotFound``.
- weights sum != 100 → ``ValueError``.
- Empty payload → ``StrategyWeightsNotFound``.

Constructor injection contract:
- ``api_url=`` may be passed for tests (otherwise env-resolved).
- ``preloaded_weights=`` may be passed for tests too (bypass HTTP entirely;
  must already be a dict matching the wire shape — used so unit tests do
  not need a live VM100 backend).
"""
from __future__ import annotations

import os
from typing import Any

import httpx


class StrategyWeightsNotFound(LookupError):
    """Raised when the VM100 endpoint returns no weights for the strategy."""


class StrategyWeightsLoader:
    """Phase 73 sibling loader to TierThresholdLoader.

    Fetches per-strategy weights from VM100 via typed REST API.
    Phase 39 lock honored: no direct VM100 DB connection.
    """

    def __init__(
        self,
        api_url: str | None = None,
        preloaded_weights: dict[str, int] | None = None,
    ):
        """Init.

        Args:
            api_url: VM100 strategy-weights endpoint URL. If None, resolved
                from ``VM100_STRATEGY_WEIGHTS_URL`` env var (KeyError on miss).
            preloaded_weights: optional dict mapping category → int weight.
                When provided, ``load(strategy_id)`` returns this dict
                verbatim — used for offline tests where running a live VM100
                backend is impractical. The sum-to-100 invariant is still
                enforced.
        """
        self._preloaded_weights = preloaded_weights
        if api_url is not None:
            self.api_url = api_url
        elif preloaded_weights is not None:
            # Preloaded mode — no URL needed.
            self.api_url = None  # type: ignore[assignment]
        else:
            # Fail-fast: env var must be set for live mode.
            self.api_url = os.environ["VM100_STRATEGY_WEIGHTS_URL"]

    def load(self, strategy_id: str) -> dict[str, int]:
        """Return the per-category weights map for ``strategy_id``.

        Returns:
            dict like {"session_fit": 10, "macro_fit": 15, ...} summing to 100.

        Raises:
            StrategyWeightsNotFound: VM100 returned empty or unknown strategy.
            ValueError: weights don't sum to 100 (replay invariant).
            httpx.HTTPError: network failure → re-raised as
                StrategyWeightsNotFound (callers want one exception type).
        """
        weights = self._fetch_weights(strategy_id)
        if not weights:
            raise StrategyWeightsNotFound(
                f"Empty weights payload for strategy_id={strategy_id!r}"
            )
        total = sum(weights.values())
        if total != 100:
            raise ValueError(
                f"Weights for strategy_id={strategy_id!r} sum to {total}, "
                f"expected 100. Phase 73 baseline replay invariant violated."
            )
        return weights

    def _fetch_weights(self, strategy_id: str) -> dict[str, int]:
        """Internal: resolve weights via preloaded dict OR HTTP GET."""
        if self._preloaded_weights is not None:
            # Offline/test path — return the preloaded dict (caller-owned).
            return dict(self._preloaded_weights)

        try:
            resp = httpx.get(
                self.api_url,
                params={"strategy_id": strategy_id},
                timeout=10.0,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            # Project lock: no silent default — fail-fast.
            raise StrategyWeightsNotFound(
                f"Cannot load weights for strategy_id={strategy_id!r} "
                f"from {self.api_url}: {exc}"
            ) from exc

        payload: dict[str, Any] = resp.json()
        weights = payload.get("weights")
        if weights is None:
            raise StrategyWeightsNotFound(
                f"VM100 returned no 'weights' field for "
                f"strategy_id={strategy_id!r}: payload={payload!r}"
            )
        return {str(k): int(v) for k, v in weights.items()}


__all__ = ["StrategyWeightsLoader", "StrategyWeightsNotFound"]
