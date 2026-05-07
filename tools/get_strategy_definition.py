"""get_strategy_definition — load a strategy YAML via core.agents.strategy_loader.

Phase 47.2 Tier-2 real tool. Always-fresh (no cache) per CONTEXT lock —
traders can edit strategy YAML without redeploying VM107.

Loader errors (StrategyNotFoundError / MalformedStrategyError) are returned
as non-fatal `Response(message=..., break_loop=False)` so the LLM can adapt
its reasoning instead of crashing the agent loop.
"""
from __future__ import annotations

import json

from pydantic import BaseModel

from core.agents.strategy_loader import (
    MalformedStrategyError,
    StrategyNotFoundError,
    load_strategy,
)
from helpers.tool import Response, Tool


class GetStrategyDefinitionRequest(BaseModel):
    """Lightweight request schema for the strategy-definition tool."""

    strategy_id: str


class GetStrategyDefinition(Tool):
    """LLM-callable: get_strategy_definition(strategy_id).

    Subclasses Tool (not ContractTool) because the loader returns a fully
    typed `StrategyDefinition` already and the error handling is loader-
    specific (StrategyNotFound / Malformed YAML / schema mismatch). The
    Phase 39 ContractTool pipeline isn't a fit here — we return Response
    directly from execute() in every error branch so the LLM keeps going.
    """

    async def execute(self, **kwargs) -> Response:  # noqa: D401
        # Validate args — bad input means the LLM mis-called us, not a tool bug.
        try:
            req = GetStrategyDefinitionRequest(**kwargs)
        except Exception as e:  # noqa: BLE001 — pydantic ValidationError
            return Response(
                message=f"get_strategy_definition: invalid args — {e}",
                break_loop=False,
            )

        # Load via Plan 03 strategy_loader (always-fresh per call).
        try:
            strategy = load_strategy(req.strategy_id)
        except StrategyNotFoundError as e:
            return Response(
                message=f"get_strategy_definition: {e}",
                break_loop=False,
            )
        except MalformedStrategyError as e:
            return Response(
                message=f"get_strategy_definition: {e}",
                break_loop=False,
            )

        # Happy path — JSON-dump the typed StrategyDefinition for the LLM.
        return Response(
            message=json.dumps(strategy.model_dump(), indent=2, default=str),
            break_loop=False,
        )
