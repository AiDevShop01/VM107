"""
QueryRouter for intent classification and embedding space routing.

Routes queries to appropriate embedding space(s) in knowledge_base_v2
based on keyword-driven intent classification.
"""
from typing import Any


class QueryRouter:
    """
    Route queries to appropriate embedding space(s) based on intent.

    Uses keyword matching to classify query intent and determines which
    named vector spaces to search in knowledge_base_v2 collection.

    Multi-intent support: queries can match multiple categories and search
    multiple embedding spaces with weighted scoring.
    """

    INTENT_KEYWORDS = {
        "pattern": [
            "pattern", "chart", "candlestick", "support", "resistance", "breakout",
            "trend", "reversal", "wick", "engulfing", "doji", "hammer", "morning star",
            "head and shoulders", "double top", "double bottom", "triangle", "flag",
            "pennant", "wedge", "channel", "trendline", "fibonacci"
        ],
        "quant": [
            "quantitative", "backtest", "sharpe", "sortino", "drawdown", "kelly",
            "monte carlo", "variance", "covariance", "regression", "statistical",
            "algorithm", "optimize", "portfolio", "correlation", "r-squared"
        ],
        "volatility": [
            "volatility", "VIX", "options", "implied", "historical vol",
            "straddle", "strangle", "Greeks", "delta", "gamma", "theta", "vega",
            "skew", "smile", "term structure", "ATR"
        ],
        "macro": [
            "macro", "fed", "gdp", "inflation", "interest rate", "monetary policy",
            "fiscal", "employment", "CPI", "yield curve", "central bank", "QE",
            "recession", "expansion", "cycle", "geopolitical"
        ],
        "microstructure": [
            "liquidity", "bid-ask", "order flow", "market impact", "spread",
            "depth", "level 2", "tape", "tick", "execution", "slippage",
            "market maker", "dark pool", "HFT", "latency"
        ],
    }

    def __init__(self, config: dict[str, Any] | None = None):
        """
        Initialize QueryRouter.

        Args:
            config: Optional configuration dict (reserved for future use)
        """
        self.config = config or {}

    def classify_intent(self, query: str) -> list[str]:
        """
        Classify query intent via keyword matching.

        Returns list of embedding space names to search. Query is lowercased
        for matching. Multiple intents can be detected.

        Args:
            query: User query string

        Returns:
            List of embedding space names (e.g., ["pattern_embedding", "general_embedding"])
        """
        query_lower = query.lower()

        # Count matches for each intent category
        intent_matches: dict[str, int] = {}

        for intent_name, keywords in self.INTENT_KEYWORDS.items():
            match_count = sum(1 for keyword in keywords if keyword in query_lower)
            if match_count > 0:
                intent_matches[intent_name] = match_count

        # Convert intent names to embedding space names
        # Sort by match count descending to get primary intent first
        sorted_intents = sorted(
            intent_matches.items(),
            key=lambda x: x[1],
            reverse=True
        )

        # Map intent names to embedding space names
        space_names = [f"{intent}_embedding" for intent, _ in sorted_intents]

        # If no matches, default to general_embedding
        if not space_names:
            space_names = ["general_embedding"]

        return space_names

    def get_search_spaces(self, query: str) -> list[dict[str, Any]]:
        """
        Returns list of {space_name, weight} dicts for multi-space search.

        Primary intent (most keyword matches) gets weight 1.0.
        Secondary intents get weight 0.5.
        If no match, returns general_embedding with weight 1.0.

        Args:
            query: User query string

        Returns:
            List of dicts with "space" and "weight" keys
            Example: [{"space": "pattern_embedding", "weight": 1.0},
                     {"space": "volatility_embedding", "weight": 0.5}]
        """
        query_lower = query.lower()

        # Count matches for each intent category
        intent_matches: dict[str, int] = {}

        for intent_name, keywords in self.INTENT_KEYWORDS.items():
            match_count = sum(1 for keyword in keywords if keyword in query_lower)
            if match_count > 0:
                intent_matches[intent_name] = match_count

        # If no matches, return general_embedding
        if not intent_matches:
            return [{"space": "general_embedding", "weight": 1.0}]

        # Sort by match count descending
        sorted_intents = sorted(
            intent_matches.items(),
            key=lambda x: x[1],
            reverse=True
        )

        # Build result list with weights
        # Primary intent (first) gets weight 1.0, others get 0.5
        result = []
        for idx, (intent_name, _) in enumerate(sorted_intents):
            space_name = f"{intent_name}_embedding"
            weight = 1.0 if idx == 0 else 0.5
            result.append({"space": space_name, "weight": weight})

        return result
