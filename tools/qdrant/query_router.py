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

    Also detects graph-oriented queries for Neo4j graph expansion.
    """

    GRAPH_INTENT_KEYWORDS = [
        "relationship", "leads to", "causes", "precede", "depends on",
        "after", "before", "connected", "related to", "path from",
        "what happens", "result of", "consequence", "prerequisite",
        "precondition", "followed by", "triggers", "requires",
        "what comes", "what leads", "sequence", "flow", "chain"
    ]

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

    # Small domain term lookup for concept extraction (lightweight, not full NER)
    DOMAIN_TERMS = [
        "breakout", "liquidity_sweep", "compression", "displacement",
        "swing", "structure", "trend", "consolidation", "reversal",
        "volatility", "momentum", "exhaustion", "retracement",
        "support", "resistance", "fair_value_gap", "fvg",
        "order_block", "imbalance", "liquidity", "stop_hunt",
        "ATR", "RSI", "MACD", "EMA", "SMA", "bollinger", "stochastic",
        "fibonacci", "elliott_wave", "wyckoff", "VSA", "accumulation",
        "distribution", "markup", "markdown", "manipulation"
    ]

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

    def should_expand_graph(self, query: str) -> bool:
        """
        Detect if query is asking about relationships.

        Checks if query contains any graph intent keywords (case-insensitive).
        Returns True if relationship-oriented query detected.

        Args:
            query: User query string

        Returns:
            True if graph expansion should be triggered

        Examples:
            >>> router = QueryRouter()
            >>> router.should_expand_graph("what leads to breakout?")
            True
            >>> router.should_expand_graph("tell me about RSI")
            False
        """
        query_lower = query.lower()
        return any(keyword in query_lower for keyword in self.GRAPH_INTENT_KEYWORDS)

    def extract_concepts_from_query(self, query: str) -> list[str]:
        """
        Extract likely concept names from query for graph lookups.

        Uses simple heuristic: find words/phrases that match known domain terms
        from small lookup set. This is lightweight — not full NER.

        Args:
            query: User query string

        Returns:
            List of concept name strings (empty if none found)

        Examples:
            >>> router = QueryRouter()
            >>> router.extract_concepts_from_query("what leads to breakout?")
            ['breakout']
            >>> router.extract_concepts_from_query("how do liquidity sweep and compression interact?")
            ['liquidity_sweep', 'compression']
        """
        query_lower = query.lower()
        concepts = []

        for term in self.DOMAIN_TERMS:
            # Check for exact match (case-insensitive)
            if term in query_lower:
                concepts.append(term)

        # Remove duplicates while preserving order
        seen = set()
        unique_concepts = []
        for concept in concepts:
            if concept not in seen:
                seen.add(concept)
                unique_concepts.append(concept)

        return unique_concepts
