"""Phase 47.3 — EvaluationContext.

The single Pydantic input to every category evaluator. Built by the runner
from Tier-1 + Tier-2 outputs. Frozen + extra='forbid' so evaluators can't
accidentally mutate state (OQ-2 lock).

``is_capability_unavailable(tool, timeframe=None)`` is the load-bearing helper
the Confidence Degradation Rule consults to decide whether to dock confidence.
The optional ``timeframe`` filter (CF-1) prevents double-docking when multiple
categories share a tool fired at different timeframes (e.g., ``get_primitives``
at H1 + M15 + M5).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from fingpt_core.contracts.agents.liquidity_context import GetLiquidityContextResponse
from fingpt_core.contracts.agents.not_available import NotAvailableResponse
from fingpt_core.contracts.agents.strategy_definition import StrategyDefinition
from fingpt_core.contracts.features.primitives_v1 import GetPrimitivesV1Response


class EvaluationContext(BaseModel):
    """Read-only input to every category evaluator (OQ-2: frozen + extra=forbid)."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", arbitrary_types_allowed=True
    )

    # Tier-1 (always present, possibly with None values)
    journal_id: str
    instrument: str
    direction: Literal["long", "short", "neutral", "avoid"]
    strategy_id: Optional[str] = None
    strategy: Optional[StrategyDefinition] = None
    timeframe: Optional[str] = None
    htf_timeframe: str = "H1"
    mtf_timeframe: str = "M15"

    # Journal metadata
    entry_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    planned_rr: Optional[float] = None

    # Tier-2 — full embedded-status envelopes
    primitives_h1: Optional[GetPrimitivesV1Response] = None
    primitives_m15: Optional[GetPrimitivesV1Response] = None
    primitives_m5: Optional[GetPrimitivesV1Response] = None
    liquidity_m15: Optional[GetLiquidityContextResponse] = None
    liquidity_m5: Optional[GetLiquidityContextResponse] = None

    # Tier-3 stubs (always not_available in V1)
    macro_context: Optional[NotAvailableResponse] = None
    news_context: Optional[NotAvailableResponse] = None
    regime_context: Optional[NotAvailableResponse] = None
    sentiment_context: Optional[NotAvailableResponse] = None
    performance_history: Optional[NotAvailableResponse] = None

    # === Computed convenience accessors =====================================

    def htf_layers(self) -> Optional[list]:
        """Return H1 primitives layers list when status='ok', else None."""
        if self.primitives_h1 and self.primitives_h1.status == "ok":
            assert self.primitives_h1.data is not None  # invariant from contract
            return self.primitives_h1.data.layers
        return None

    def mtf_layers(self) -> Optional[list]:
        """Return M15 primitives layers list when status='ok', else None."""
        if self.primitives_m15 and self.primitives_m15.status == "ok":
            assert self.primitives_m15.data is not None
            return self.primitives_m15.data.layers
        return None

    def m5_layers(self) -> Optional[list]:
        """Return M5 primitives layers list when status='ok', else None."""
        if self.primitives_m5 and self.primitives_m5.status == "ok":
            assert self.primitives_m5.data is not None
            return self.primitives_m5.data.layers
        return None

    def is_capability_unavailable(
        self,
        tool: str,
        timeframe: Optional[str] = None,
    ) -> bool:
        """Phase 47.3 + CF-1: True if the named tool returned not_available.

        For tools fired at multiple timeframes (``get_primitives`` H1/M15/M5,
        ``get_liquidity_context`` M15/M5), the optional ``timeframe`` filter
        narrows to a single envelope. ``timeframe=None`` returns True if ANY
        invocation returned not_available — useful for Tier-3 stubs that fire
        once.
        """
        # get_primitives — 3 invocations across timeframes
        if tool == "get_primitives":
            envelopes: list[Optional[GetPrimitivesV1Response]] = []
            if timeframe in (None, "H1"):
                envelopes.append(self.primitives_h1)
            if timeframe in (None, "M15"):
                envelopes.append(self.primitives_m15)
            if timeframe in (None, "M5"):
                envelopes.append(self.primitives_m5)
            for env in envelopes:
                if env is not None and env.status == "not_available":
                    return True
            return False

        # get_liquidity_context — 2 invocations
        if tool == "get_liquidity_context":
            liq_envelopes: list[Optional[GetLiquidityContextResponse]] = []
            if timeframe in (None, "M15"):
                liq_envelopes.append(self.liquidity_m15)
            if timeframe in (None, "M5"):
                liq_envelopes.append(self.liquidity_m5)
            for env in liq_envelopes:
                if env is not None and env.status == "not_available":
                    return True
            return False

        # Tier-3 stubs — single invocation each
        stub_map: dict[str, Optional[NotAvailableResponse]] = {
            "get_macro_context": self.macro_context,
            "get_news_context": self.news_context,
            "get_regime_context": self.regime_context,
            "get_sentiment_context": self.sentiment_context,
            "get_performance_history": self.performance_history,
        }
        if tool not in stub_map:
            # Tool not in ctx — caller's bug; conservative: don't dock.
            return False
        env = stub_map[tool]
        if env is None:
            # Tier-3 stub envelope absent — treat as unavailable (V1 always
            # returns not_available for these tools, so absence is equivalent).
            return True
        # NotAvailableResponse always has status='not_available'
        return getattr(env, "status", "not_available") == "not_available"
